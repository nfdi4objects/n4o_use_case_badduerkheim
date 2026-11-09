* Tabelle (SQL-DB, Excel, CSV)
  -   Eine Zeile ist eine formatierte Anordnung von typisierten Werten
      Datenzeile Bsp.: 'Heinz Müller','37083 Göttingen','1999-01-10',1.92m,TRUE,23456
  -   Tabelle ist ein Array aus einer Kopfzeile und vielen Datenzeilen
      Kopfzeile Bsp.: 'Name', 'Wohnort', 'Geburtsdatum', 'Größe', 'verheiratet','ID'
  -   Kopfzeile beinhaltet Semantik und Typ für alle Datenzeilen
  -   Schlüssel sind eindeutige IDs zum Referenzieren der Zeilen
  -   Schnittstelle: Kopfzeile, Zeile (ID), Spalte (Kopf), Element (Kopf,ID)
  -   Aggregatzustand: fest
  -   kompakt, schnell, statisch, schnelles anhängen
  -   nicht dynamisch, schwer erweiterbar

* Objekte (JSON)
  -   Eine Eigenschaft ist ein typisiertes Schlüssel-Werte Paar 
  Bsp.: geburtsdatum:1999-04-31
  -   Objekte bestehen aus Liste von Eigenschaften
  -   Objekte können in verschiedenen Container wohnen (Listen, Arrays,Maps, Sets)
  -   Jedes Objekt ist wie eine einzeilige Tabelle
  -   Schnittstelle: Container-Schnittstelle, Schlüssel
  -   Aggregatzustand: flüssig
  -   Variable Zusammenstellung, dynamisch, leicht zu erweitern
  -   Langsamer, redundant

* Tripels (RDF)
  -   S, P, O Format mit URI und Literalen
  S = ID, P = Semantik, O = Wert + Typ
  -   Jedes Triple ist wie ein Objekt mit einer Eigenschaft
  -   Tripels leben in einem Triple-Store
  -   Aggregatzustand: gasförmig
  -   Beliebig erweiterbar, impliziter Graph
  -   Langsamer, sehr redundant
