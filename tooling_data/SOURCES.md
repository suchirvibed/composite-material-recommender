# Tool-material database — sources and assumptions

`tool_materials.csv` is deliverable **D1** of the Matrix Engine Report
(mold material property database, every value sourced). Source keys used in
the `sources` column:

| Key | Source |
|---|---|
| HTM | High Temp Metals, *Invar 36 technical data* (Carpenter Invar 36), hightempmetals.com/techdata/hitempInvar36data.php — mean CTE 1.30 / 2.11 / 4.18 / 7.60 µm/m·°C at 93 / 149 / 260 / 371 °C; 8055 kg/m³; 515 J/kg·K; 10.5 W/m·K |
| PROTOLABS | Proto Labs CNC material data sheet, Aluminum 6061-T651/T6 — 23.6 µm/m·K (20–100 °C), 2.70 g/cm³, 896 J/kg·K, 167 W/m·K |
| MATMATCH / MAKEITFROM | ASTM A36 entries — density 7.8–7.9 g/cm³, CTE 11–13.8 µm/m·K, 465–470 J/kg·K, 50 W/m·K |
| ULBRICH | Ulbrich, *Nickel 200 UNS N02200* data sheet — 13.3 µm/m·K (27–93 °C), 8.89 g/cm³, 456 J/kg·K, 67.1 W/m·K (100 °C). Used as a proxy: electroformed nickel is not identical to wrought Nickel 200 |
| HEXTOOL | Hexcel, *HexTool User Guide* (2026), Table 1 — M61 CTE 4 ×10⁻⁶/°C X-Y, 47 Z (ASTM E289-90); Tg 275 °C dry / 230 °C wet; cured 190 °C / 7 bar; 55 % Vf, BMI |
| PATENT | US 11123899 (seaming multi-sectional composite tooling) — HexTool M61 maximum use temperature 218 °C |
| FISHER | Fisher, Levy & Kratz (2022), *Effects of heat transfer coefficient variations on composite curing*, J. Compos. Mater. 57(3) — Table 2 effective laminate density 1580 kg/m³; measured autoclave HTC means 99 W/m²K (3 bar) and 138 W/m²K (7 bar), oven mean 37 W/m²K (project folder) |
| GRAFTECH | GrafTech, *Grade ATJ graphite* GT-5028 Rev. 2 (2009) — 1.76 g/cm³, CTE 3.0 ×10⁻⁶/K (to 100 °C), 116 W/m·K |
| EASYCOMP | Easy Composites, *EB700 High Temperature Epoxy Tooling Board* TDS — 0.70 g/cm³, CTE 35–40 ×10⁻⁶/K (10–100 °C), Tg / max use 130 °C, autoclave use once sealed |
| RAMPF | RAMPF, *RAKU-TOOL WB-0950* board datasheet — ca. 0.95 g/cm³, CTE 30–35 ×10⁻⁶/K, HDT 190–200 °C (values from a search extract of the datasheet; verify against the PDF) |
| GENPLAST | CompositesWorld product news, *General Plastics launches ultrahigh-temperature tooling board* — LAST-A-FOAM FR-4800: 48 lb/ft³, CTE 13 ×10⁻⁶/°F, 204 °C continuous, 249 °C peak |
| TOOLREP | Project document *Autoclave_Prepreg_Mold_Tooling_Report.pdf*, Table 1 — cycle life (Invar "thousands", CFRP "hundreds", steel "very high", aluminium "high", nickel "high with maintenance"), Class-A use of nickel, sealing of composite tools |
| MATRIX | Project document *Matrix_Engine_Report*, worked CTE check (steel ≈ 12 µm/m·°C) |
| BOM | Project document *Autoclave Prepeg process BOM and cost.docx*, mould material options (₹ per ~1 m² mould) |

## Assumptions (stated, configurable)

- **Cycle-life numbers** map the qualitative classes of the tooling report to
  conservative minimum counts: very high / "thousands" → 1000, high → 500,
  "hundreds" → 200, medium–high board → 100. Override `cycle_life_min` with
  supplier figures when available.
- **Metal service temperature** is entered as 300–400 °C: far above any epoxy or
  BMI cure, so it never limits feasibility (engineering judgement, not a datasheet value).
- **Tool face thickness** defaults (metal 12 mm, nickel shell 6 mm, CFRP 6 mm,
  graphite 25 mm, boards 50 mm) are typical-design assumptions used for tool
  mass and thermal lag; enter the real thickness when known.
- **Tool cost** scales linearly with tool face area from the ₹/~1 m² figures.

## Known data issues

- **Mild steel ₹3k–13k** (BOM document) is 10–100× below aluminium and Invar,
  but the document's own Table 6 arithmetic uses it. It is kept as given and
  flagged UNVERIFIED in every report.
- **Not modelled**: MDF and PU tooling board appear in the BOM cost table but
  have no sourced thermal properties; add CTE / density / max temperature to
  include them.
- **Missing heat capacity / conductivity** for CFRP tooling, graphite and
  boards: thermal lag is reported as "supplier data needed" for these and the
  criterion scores 0 ("not demonstrated") in ranking, with a data-gap flag.
