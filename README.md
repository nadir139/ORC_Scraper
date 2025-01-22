# ORC_Scraper
HOw to use it : 

On line 688 : eg : url = "https://data.orc.org/public/WPub.dll/CC/168931" 
change the URL to analyse a different ORC certificate and extrapolate the JSON File. 


guarda a coprire i case studies secondo me in una giornata si coprono tutti e si riescono a ottenere I JSON completi. 

--- analizzare parte per parte : Boat name - certificate type etc. per ogni annata fino al 2018. 

Probabilmente per 2018/2019/2020 conviene fare un altro scraper. 

le altre mosse da fare sono: 

-fare data scraping di tutti I certificati in una botta, da solo il codice va in ordine per anno o per nome o per paese o come si vuole, apre il link, estrae il JSON e lo salva con Nome della barca tipo di certificato e anno direttamente in un Database tipo MongoDB o MySQL . 

- una volta che si hanno tutti i JSON nel DB si mettono in una python List cosi poi si possono analizzare/suddividere con Panda e Matplot per grafici etc.



il solver serve a estrapolare una qualche forma di dipendenza tra rated parameters e rating. per capire il peso delle variabili e scoprire quali sono potential loop-holes

molto indietro no infatti, al limite prova solo con roba 2018, solo perche' fino al 2018 c'era anche la wetted area che poi hanno tolto che pero' e' un dato molto interessante perche' non si trova mai da nessuna parte