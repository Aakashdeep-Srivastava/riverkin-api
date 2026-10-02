# RiverKin data provenance

What in RiverKin's seed data is **real** vs **synthesized**, and where it came
from. The PRD requires every simulated element to say so; this file is the
audit trail.

## OneAquaHealth research cities — REAL

OneAquaHealth (Horizon Europe GA 101086521, `oneaquahealth.eu`) runs citizen
monitoring in **five** research cities. A network of ~100 urban streams and
small rivers is being built across them.

| City | Country | Centre (lat, lng) | Source |
|------|---------|-------------------|--------|
| Coimbra | Portugal | 40.2033, −8.4103 | oneaquahealth.eu/research-cities/coimbra |
| Toulouse | France | 43.6045, 1.4440 | oneaquahealth.eu |
| Benevento | Italy | 41.1300, 14.7800 | **OAH FHIR IG** `Loc-Benevento` instance |
| Ghent | Belgium | 51.0543, 3.7174 | oneaquahealth.eu |
| Oslo | Norway | 59.9139, 10.7522 | oneaquahealth.eu (Nordre Aker: `Loc-Nordre-Aker`) |

## River / stream names — REAL

Real urban waterways in each city, sourced via public references:

- **Coimbra:** Mondego, Ribeira de Coselhas, Ribeira de Eiras, Ribeira dos
  Covões, Vale das Flores, Ribeira de Fornos, Ribeira da Arregaça, Ceira.
  (Coselhas & Eiras are named OAH community-walk streams.)
- **Toulouse:** Garonne, Touch, Hers-Mort, Girou, Canal du Midi, Canal de
  Brienne, Save.
- **Benevento:** Calore Irpino, Sabato, Tammaro, San Nicola.
- **Ghent:** Leie, Schelde, Lieve, Ketelvaart, Coupure, Muinkschelde, De Reep,
  Moervaart.
- **Oslo:** Akerselva, Hoffselven, Sognsvannsbekken, Gaustadbekken,
  Holmenbekken, Lysakerelva, Mærradalsbekken, Hovinbekken.

## Per-site coordinates — SYNTHESIZED (labelled)

OAH has **not published** the exact coordinates of the ~100 citizen sites.
`oah_sites.json` therefore places 106 sites deterministically around each real
city centre, along the real rivers (`gen_sites.py`, golden-angle spread, no
RNG → reproducible). `simulated_coordinates: true` on every row; the UI shows
"Simulated, illustrative" per the PRD hard rule.

## Field codes — REAL (OAH CodeSystem)

`oah_field_codes.json` maps RiverKin's citizen questions to the **real** OAH
code system `TemporaryOahSystem`
(`http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu`, repo
`github.com/hl7-eu/oah`): `foam` (Foam/colour/smell), `hydrology`,
`riparianVegetation`, `morophology`. Citizen-only fields with no OAH concept
(`litter`, `pipe-outfall`) are marked **proposed** — exported as a proposed
Observation.extension, exactly as the PRD describes.

## FHIR export — REAL IG

Target IG: **OneAquaHealth** `hl7.eu.fhir.oah` (FHIR R4), CI build at
`build.fhir.org/ig/hl7-eu/oah`, source `github.com/hl7-eu/oah`. Relevant
profiles: `LocationOah`, `observation-*-oah`, `group-oah`, `specimen-oah`.
Location identifier system: `https://oneaquahealth.eu/location-id`.

## Weather — REAL API

48-hour rainfall from **Open-Meteo** (`open-meteo.com`), free, no key. Pulled
per site every 3 h (PRD).
