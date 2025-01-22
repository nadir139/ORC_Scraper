import requests
from bs4 import BeautifulSoup
import json
import os

def fetch_html(url: str) -> str:
    """Fetch the raw HTML from the given URL."""
    response = requests.get(url)
    response.raise_for_status()
    return response.text

def parse_certificate_type(soup):
    """
    Handles both structures:
    
    (A) <div class="cert-type">
          <div>
            <strong></strong>
            <span>Club Certificate</span>
            <strong>2025</strong>
          </div>
        </div>
    
    (B) <div class="cert-type">
          <h1>
            Club<br><span></span>Certificate<br>
            <span class="cert-subtype"></span>
            <strong>2024</strong>
          </h1>
        </div>
    
    Returns:
      {
        "certificate_type": "Club Certificate",
        "year": "2024"   # or "2025", etc.
      }
    or None if not found.
    """
    cert_div = soup.find("div", class_="cert-type")
    if not cert_div:
        return None

    # Check if there's a <div> or <h1> child
    # We'll pick whichever we find
    inner_div = cert_div.find("div")  # structure A
    inner_h1  = cert_div.find("h1")   # structure B

    container = inner_div if inner_div else inner_h1
    if not container:
        return None

    # 1) Find all <strong> children to extract the year from the *last* <strong>.
    strongs = container.find_all("strong")
    year_text = ""
    if strongs:
        year_text = strongs[-1].get_text(strip=True)

    # 2) We'll gather text from the container but *ignore* the last <strong>,
    #    so we don’t double-count the year in the certificate_type.
    #    One approach is to temporarily remove the <strong> node from the DOM,
    #    get text, then revert or just skip it in code.

    # Let's copy the container, remove the strong(s), then get_text().
    # Or simpler: let's just get_text() from all *non-strong* elements.
    # We'll also skip script/style, etc.

    # A quick approach: clone container, decompose the <strong> tags
    import copy
    from bs4 import NavigableString

    container_clone = copy.copy(container)  # shallow copy
    # Actually we want a deep copy so we can decompose
    # Let's parse the container's HTML anew:
    container_clone_soup = BeautifulSoup(str(container), "html.parser")
    for st in container_clone_soup.find_all("strong"):
        st.decompose()

    # Now get text from the clone
    raw_text = container_clone_soup.get_text(separator=" ", strip=True)
    # e.g. "Club Certificate" or "Club  Certificate" with extra spaces

    # 3) Clean up the raw text: remove extra spaces, line breaks, etc.
    # Possibly "Club  Certificate" -> "Club Certificate".
    # A simple approach is to split and re-join:
    words = raw_text.split()
    cert_type_text = " ".join(words)

    return {
        "certificate_type": cert_type_text,
        "year": year_text
    }

def parse_boat_name_and_sail(soup):
    cert_divs = soup.find_all("div", class_="cert-type")
    if len(cert_divs) < 2:
        return None  # Not enough blocks
    # The second block
    boat_div = cert_divs[1]

    strong_elem = boat_div.find("strong")
    span_elem   = boat_div.find("span")
    if strong_elem and span_elem:
        return {
            "boat_name": strong_elem.get_text(strip=True),
            "sail_number": span_elem.get_text(strip=True),
        }
    return None

def parse_right_column(soup):
    """
    Parses the <div class="right-column"> section of the HTML, extracting:
      1) "summary_top" fields from <div class="tabular1"> (APH ToD, CDL, etc.)
      2) Each p1group block (BOAT, HULL, PROPELLER, etc.), capturing label/data pairs
         within <div class="tabular2/3/5">.
      3) A special fallback for the COMMENTS block (which may not have label/data pairs).
    
    Returns a dict:
      {
        "summary_top": {
          "APH ToD": "...",
          "CDL": "...",
          "APH ToT": "...",
          ...
        },
        "groups": [
          {
            "title": "BOAT",
            "items": [ {"label": "...", "value": "..."}, ... ]
          },
          {
            "title": "HULL",
            "items": [...],
          },
          ...
        ]
      }
    or None if .right-column is not found.
    """
    right_col = soup.find("div", class_="right-column")
    if not right_col:
        return None  # No right column at all

    # ------------------------------------------------
    # 1) Parse the top summary fields from <div class="tabular1">
    #    e.g. APH ToD: 466.3, CDL: 11.263, ...
    # ------------------------------------------------
    summary_top = {}
    tabular1 = right_col.find("div", class_="tabular1")
    if tabular1:
        labels = tabular1.find_all("span", class_="small-label")
        for lbl in labels:
            label_text = lbl.get_text(strip=True).replace(":", "").strip()

            # parent_span => <span class="number"> that wraps small-label
            parent_span = lbl.find_parent("span", class_="number")
            if not parent_span:
                continue

            # Next sibling might be <span class="data number"> or
            # <span class="number"> <span class="data">someVal</span> </span>
            next_el = parent_span.find_next_sibling("span")
            if not next_el:
                value_text = ""
            else:
                # Check the classes on next_el
                classes = next_el.get("class") or []
                if "data" in classes:
                    # e.g. <span class="data number">someVal</span>
                    value_text = next_el.get_text(strip=True)
                elif "number" in classes:
                    # e.g. <span class="number"><span class="data">70701</span></span>
                    inner_data = next_el.find("span", class_="data")
                    value_text = inner_data.get_text(strip=True) if inner_data else ""
                else:
                    # Some unexpected structure
                    value_text = next_el.get_text(strip=True)

            summary_top[label_text] = value_text

    # ------------------------------------------------
    # 2) Parse each <div class="p1group"> block
    #    We'll store them in a list => "groups"
    # ------------------------------------------------
    groups_data = []
    p1_groups = right_col.find_all("div", class_="p1group", recursive=False)
    # (If you need to catch nested p1group, remove recursive=False,
    #  but typically they're siblings in your snippet.)
    for group in p1_groups:
        # Each group may have <span class="title"> text
        title_span = group.find("span", class_="title")
        if title_span:
            group_title = title_span.get_text(strip=True)
        else:
            # fallback
            group_title = "No title"

        # Now find tabular2 / tabular3 / tabular5 inside
        # We'll gather label/data pairs
        # If there's no tabularX, it might be a "COMMENTS" block, etc.
        tab_div = None
        for possible_class in ["tabular2", "tabular3", "tabular5"]:
            tab_div = group.find("div", class_=possible_class)
            if tab_div:
                break

        items = []
        if tab_div:
            # Typical label/data pairs, e.g.
            #   <span class="label">Class</span><span class="data">Mat 11.80</span>
            labels = tab_div.find_all("span", class_="label")
            datas  = tab_div.find_all("span", class_="data")

            # Usually they line up in pairs
            for lbl, dat in zip(labels, datas):
                label_text = lbl.get_text(strip=True)
                value_text = dat.get_text(strip=True)
                items.append({"label": label_text, "value": value_text})
        else:
            # Possibly a block with free-text comments
            # If it's the "COMMENTS" block, let's just store each text line
            # in items under a single label "Comment".
            # We can do something like:
            text_spans = group.find_all("span", recursive=True)
            # e.g. <span style="display:block;">IRC ENDORSED 2024</span>
            # We'll gather them into one or more items:
            # Check if there's any text in these spans that isn't label/data:
            big_text = []
            for sp in text_spans:
                # If it has class_ in ["label","data","title"], skip or handle differently
                if not any(cls in ["label","data","title"] for cls in (sp.get("class") or [])):
                    txt = sp.get_text(strip=True)
                    if txt:
                        big_text.append(txt)
            if big_text:
                # Join them or store them as separate lines
                combined = "\n".join(big_text)
                items.append({"label": "Comment", "value": combined})

        groups_data.append({
            "title": group_title,
            "items": items
        })

    # Return everything
    return {
        "summary_top": summary_top,
        "groups": groups_data
    }

def parse_boatspeeds_table(soup):
    """
    Finds the <table class="boatspeeds"> that contains:
      - A "Wind Velocity" row (the first row)
      - Subsequent rows with class="data" (Beat Angles, Beat VMG, etc.)

    Returns a dict like:
      {
        "wind_speeds": ["4 kt", "6 kt", "8 kt", ...],
        "rows": [
          { "label": "Beat Angles", "values": ["42.9°", "42.9°", ...] },
          { "label": "Beat VMG",    "values": ["3.06", "4.23", ...] },
          ...
        ]
      }
    or None if not found.
    """

    # 1) Locate the table by class
    table = soup.find("table", class_="boatspeeds")
    if not table:
        return None  # Not found

    # 2) Grab all rows
    rows = table.find_all("tr")
    if len(rows) < 2:
        # We expect at least one row for "Wind Velocity" and more for data
        return None

    # 3) The first row has the wind speeds (plus the label "Wind Velocity")
    header_cells = rows[0].find_all("td")
    if not header_cells:
        return None
    # skip the first cell which is "Wind Velocity"
    wind_speeds = [td.get_text(strip=True) for td in header_cells[1:]]

    data_rows = []
    # 4) Each subsequent row is presumably class="data"
    for row in rows[1:]:
        if "data" not in (row.get("class") or []):
            # skip if not data row
            continue

        cells = row.find_all("td")
        if not cells:
            continue
        label = cells[0].get_text(strip=True)    # e.g. "Beat Angles", or "52°"
        values = [c.get_text(strip=True) for c in cells[1:]]
        data_rows.append({"label": label, "values": values})

    return {
        "wind_speeds": wind_speeds,
        "rows": data_rows
    }

def parse_time_allowances_secsnm(soup):
    """
    Parses the <table class="allowances"> block that has <caption>Time Allowances in secs/NM</caption>.
    The table is structured like:

      <tr class="title">
        <th>Wind Velocity</th>
        <td>4 kt</td><td>6 kt</td>...<td>24 kt</td>
      </tr>

      <tr class="data">
        <th>Beat VMG</th>
        <td>1177.6</td><td>851.0</td>...
      </tr>
      ...
      <tr class="data">
        <th>Run VMG</th>
        <td>1150.3</td><td>806.1</td>...
      </tr>

      <tr class="title">
        <th colspan="99">Selected Courses</th>
      </tr>
      <tr class="data">
        <th>Windward / Leeward</th>
        <td>1163.7</td><td>828.6</td>...
      </tr>
      <tr class="data">
        <th>All purpose</th>
        <td>873.4</td><td>638.3</td>...
      </tr>

    Returns:
      {
        "wind_speeds": [...],
        "rows": [ {"label":..., "values":[...]} , ... ],
        "selected_courses": [ {"label":..., "values":[...]} , ... ]
      }
    or None if not found.
    """
    # 1) Locate the table by searching for caption "Time Allowances in secs/NM"
    table = None
    candidate_tables = soup.find_all("table", class_="allowances")
    for t in candidate_tables:
        cap = t.find("caption")
        if cap and "Time Allowances in secs/NM" in cap.get_text(strip=True):
            table = t
            break
    if not table:
        return None  # Not found

    # 2) Grab all <tr> within this table
    rows = table.find_all("tr")
    if not rows:
        return None

    # We'll store the results in three parts:
    wind_speeds = []
    main_rows = []
    selected_courses = []

    # 3) The first row with class="title" should contain Wind Velocity
    #    and the columns for wind speeds
    #    e.g. <th>Wind Velocity</th><td>4 kt</td><td>6 kt</td>...
    wind_velocity_row = None
    i = 0
    for i, r in enumerate(rows):
        row_classes = r.get("class", [])
        if "title" in row_classes:
            # Check if there's "Wind Velocity" in the first TH
            first_th = r.find("th")
            if first_th and "Wind Velocity" in first_th.get_text(strip=True):
                wind_velocity_row = r
                break
    if not wind_velocity_row:
        return None  # Didn't find the "Wind Velocity" row

    # from that row, skip the first cell (the <th> Wind Velocity)
    velocity_cells = wind_velocity_row.find_all(["th", "td"])
    wind_speeds = [cell.get_text(strip=True) for cell in velocity_cells[1:]]

    # 4) Now parse subsequent .data rows until we hit another .title row that says "Selected Courses"
    main_data_rows = []
    selected_courses_rows = []
    in_selected_courses = False

    for r in rows[i+1:]:
        row_class = r.get("class", [])
        if "title" in row_class:
            # check if it has "Selected Courses"
            if "Selected Courses" in r.get_text(strip=True):
                in_selected_courses = True
            continue

        if "data" in row_class:
            # Each data row: first cell is label, rest are values
            cells = r.find_all(["th", "td"])
            if len(cells) > 1:
                label = cells[0].get_text(strip=True)
                values = [c.get_text(strip=True) for c in cells[1:]]
                if not in_selected_courses:
                    main_data_rows.append({"label": label, "values": values})
                else:
                    selected_courses_rows.append({"label": label, "values": values})

    # Return the structured result
    return {
        "wind_speeds": wind_speeds,
        "rows": main_data_rows,
        "selected_courses": selected_courses_rows
    }

def parse_single_number_scoring(soup):
    """
    Finds the table <table class="allowances" id="singlenumber">, which has a caption
    'Single Number Scoring Options' and columns:
      - 'Course'
      - 'Time On Distance'
      - 'Time On Time'

    Example structure:

      <tr class="title">
        <th>Course</th>
        <th>Time On<br>Distance</th>
        <th>Time On<br>Time</th>
      </tr>
      <tr class="data">
        <th>Windward / Leeward</th>
        <td>576.0</td>
        <td>1.0417</td>
      </tr>
      <tr class="data">
        <th>All purpose</th>
        <td>466.3</td>
        <td>1.2866</td>
      </tr>

    Returns:
      {
        "caption": "Single Number Scoring Options",
        "columns": ["Time On Distance", "Time On Time"],
        "rows": [
          { "label": "Windward / Leeward", "values": ["576.0", "1.0417"] },
          { "label": "All purpose",        "values": ["466.3", "1.2866"] }
        ]
      }
    or None if not found.
    """
    # Locate the table by id="singlenumber" or by searching for the caption
    table = soup.find("table", class_="allowances", id="singlenumber")
    if not table:
        return None

    # Read the caption (if present)
    cap_elem = table.find("caption")
    caption_text = cap_elem.get_text(strip=True) if cap_elem else ""

    # The first row with class="title" should define the columns
    title_row = table.find("tr", class_="title")
    if not title_row:
        return None

    # The first <th> is "Course". Skip it; the next ones are the scoring columns
    headers = title_row.find_all("th")
    if len(headers) < 2:
        return None

    # columns are from headers[1:] (skipping "Course")
    columns = []
    for h in headers[1:]:
        # e.g. "Time OnDistance\nTime" from the <br>, we'll strip and maybe rejoin
        col_text = h.get_text(separator=" ", strip=True)
        columns.append(col_text)

    # Now parse each row with class="data"
    data_rows = table.find_all("tr", class_="data")

    rows_data = []
    for row in data_rows:
        cells = row.find_all(["th","td"])
        if len(cells) < 3:
            # at least 1 label + 2 values
            continue

        # The first cell is the label (e.g. "Windward / Leeward")
        label = cells[0].get_text(strip=True)
        # The rest are the numeric values for columns
        values = [c.get_text(strip=True) for c in cells[1:]]

        rows_data.append({
            "label": label,
            "values": values
        })

    return {
        "caption": caption_text,
        "columns": columns,
        "rows": rows_data
    }


def parse_boat_specs(soup: BeautifulSoup):
    """
    Extract boat specs from <div class="p2group"> sections.
    Returns a list of dicts with keys: section_title, label, value.
    """
    data_list = []
    p2groups = soup.find_all("div", class_="p2group")
    for group in p2groups:
        title_elem = group.find("span", class_="title")
        section_title = title_elem.get_text(strip=True) if title_elem else "Unknown Section"

        labels = group.find_all("span", class_="label")
        datas  = group.find_all("span", class_="data")

        for lbl, dat in zip(labels, datas):
            data_list.append({
                "section_title": section_title,
                "label": lbl.get_text(strip=True),
                "value": dat.get_text(strip=True)
            })

    return data_list
"""
def parse_scoring_options(soup: BeautifulSoup):
    
    Extract scoring options from each <div class="scoringparent">
    that contains <table class="allowances">.
    
    Returns list[dict] with:
      {
        "country_id": "countryEST",
        "table_index": 0,
        "row_values": ["Triple Number Coastal/Long Distance Low", "585.4", "1.0250"]
      }
    
    scoring_data = []
    scoring_parents = soup.find_all("div", class_="scoringparent")
    for parent in scoring_parents:
        country_id = parent.get("id")  # e.g. "countryEST"
        tables = parent.find_all("table", class_="allowances")
        for t_index, table in enumerate(tables):
            rows = table.find_all("tr", class_="data")
            for row in rows:
                cells = row.find_all(["th", "td"])
                row_texts = [c.get_text(strip=True) for c in cells]
                scoring_data.append({
                    "country_id": country_id,
                    "table_index": t_index,
                    "row_values": row_texts
                })

    return scoring_data
"""

def parse_sails(soup: BeautifulSoup):
    """
    Extract sail data from each <div class="sailsGroup"> block.
    We'll store each row as a dictionary keyed by column name:
    {
      "sail_type": "MAINSAIL",
      "entries": [
         { "Id": "1", "MHB": "1.16", "MUW": "1.78", ... },
         ...
      ]
    }
    """
    sails_info = []

    sails_groups = soup.find_all("div", class_="sailsGroup")
    for group in sails_groups:
        title_elem = group.find("span", class_="title")
        if not title_elem:
            continue
        sail_type = title_elem.get_text(strip=True)

        tabular_div = group.find("div", class_="tabular")
        if not tabular_div:
            # Might be style="display:none", so skip
            continue

        # Column headers
        col_titles = [ct.get_text(strip=True) for ct in tabular_div.find_all("span", class_="coltitle")]
        num_cols = len(col_titles)

        # If no columns found, skip or handle differently
        if num_cols == 0:
            # If there's truly no columns, it might be a group with no data
            # You could just skip adding an entry or add an empty one
            sails_info.append({
                "sail_type": sail_type,
                "entries": []
            })
            continue

        # Data cells
        data_spans = tabular_div.find_all("span", class_="data")
        rows_as_dicts = []
        for i in range(0, len(data_spans), num_cols):
            chunk = data_spans[i : i + num_cols]
            if len(chunk) < num_cols:
                break
            row_dict = {}
            for j, ds in enumerate(chunk):
                key = col_titles[j]
                value = ds.get_text(strip=True)
                row_dict[key] = value
            rows_as_dicts.append(row_dict)

        sails_info.append({
            "sail_type": sail_type,
            "entries": rows_as_dicts
        })

    return sails_info
""" 
def parse_time_allowances(soup: BeautifulSoup):
    
    Extract the "Time Allowances in secs/NM" table, often stored in a table with
    class="boatspeeds" (or similarly named). The rows might look like:
      <tr class="title"><th>Wind Velocity</th><th>4</th><th>6</th>...</tr>
      <tr class="data" code="OC" scoringkind="pcs">
         <th>Coastal/Long Distance</th>
         <td windspeed="4">1230.3</td>
         <td windspeed="6">826.3</td> ...
      </tr>
    
    We'll parse these into a structure like:
      {
        "wind_speeds": ["4", "6", "8", "10", "12", "14", ...],
        "rows": [
          {
            "label": "Coastal/Long Distance",
            "values": ["1230.3", "826.3", "633.7", ...]
          },
          ...
        ]
      }

    If there's more than one such table, adapt to parse them all or pick the first, etc.
    
    # Try to find a table by class="boatspeeds"
    table = soup.find("table", class_="boatspeeds")
    if not table:
        # Not found, return empty or None
        return None

    # We'll look for the header row (often tr.title)
    header_tr = table.find("tr", class_="title")
    if not header_tr:
        return None

    # The first <th> might say "Wind Velocity" or "Time Allowances in secs/NM"
    # Then the subsequent <th> or <td> might be wind speeds: "4", "6", "8"...
    # We'll gather them:
    header_cells = header_tr.find_all(["th","td"])
    # Skip the first cell if it's just a label
    # The rest are wind speeds:
    wind_speeds = [cell.get_text(strip=True) for cell in header_cells[1:]]

    # Now get the data rows (class="data")
    data_rows = []
    for row in table.find_all("tr", class_="data"):
        cells = row.find_all(["th","td"])
        if not cells:
            continue
        # The first cell is the label (e.g. "Coastal/Long Distance")
        label = cells[0].get_text(strip=True)
        # The rest are time allowance values
        values = [c.get_text(strip=True) for c in cells[1:]]
        data_rows.append({
            "label": label,
            "values": values
        })

    return {
        "wind_speeds": wind_speeds,
        "rows": data_rows
    }
"""
def main():
    # 1) Fetch the HTML
    url = "https://data.orc.org/public/WPub.dll/CC/168931"
    html = fetch_html(url)

    # 2) Parse with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # 3) Extract data sets
    certificate_type = parse_certificate_type(soup)
    boatname_sailn = parse_boat_name_and_sail(soup)
    right_column = parse_right_column(soup)
    boatspeeds_table = parse_boatspeeds_table(soup)
    time_allowances_table = parse_time_allowances_secsnm(soup)
    single_number_scoring = parse_single_number_scoring(soup)
    boat_specs = parse_boat_specs(soup)

    #scoring_options = parse_scoring_options(soup)
    sails_data      = parse_sails(soup)
    #time_allowances = parse_time_allowances(soup)

    # 4) Combine everything into a single JSON structure
    orc_data = {
        "certificate_type": certificate_type,
        "boatname_sailn" : boatname_sailn,
        "right_column": right_column,
        "boatspeeds_table": boatspeeds_table,
        "time_allowances_table": time_allowances_table,
        "single_number_scoring": single_number_scoring,
        "boat_specs": boat_specs,
        #"scoring_options": scoring_options,
        "sails": sails_data,
        #"time_allowances": time_allowances
    }

        # -- Construct the desired file name --
    # 1) Get boat name (fall back if not found)
    if boatname_sailn and "boat_name" in boatname_sailn:
        boat_name = boatname_sailn["boat_name"]
    else:
        boat_name = "UnknownBoat"

    # 2) Get year and cert type
    if certificate_type:
        year = certificate_type.get("year", "UnknownYear")
        cert_type_str = certificate_type.get("certificate_type", "UnknownType")
    else:
        year = "UnknownYear"
        cert_type_str = "UnknownType"

    # 3) Remove spaces or special chars in the filename
    boat_name_safe = boat_name.replace(" ", "_")
    cert_type_safe = cert_type_str.replace(" ", "_")

    # 4) Create the final filename
    filename = f"orc_certificate_{boat_name_safe}_{year}_{cert_type_safe}.json"

    # -- Ensure we write into the "JSON_certificates" subfolder --
    os.makedirs("JSON_certificates", exist_ok=True)  # creates folder if missing
    save_path = os.path.join("JSON_certificates", filename)

    # 5) Write out the JSON file
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(orc_data, f, ensure_ascii=False, indent=2)

    print(f"Done! Your JSON is saved at: c:/Users/nadir/OneDrive/Desktop/ORC data scraper/JSON_certificates")

"""
    # 5) Write it out to a JSON file
    with open("orc_certificate_data.json", "w", encoding="utf-8") as f:
        json.dump(orc_data, f, ensure_ascii=False, indent=2)

    print("Done! Check 'orc_certificate_data.json' in the current directory.")
"""
if __name__ == "__main__":
    main()
