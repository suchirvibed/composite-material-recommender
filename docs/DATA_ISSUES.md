# Data issues and gaps

Found while turning the project documents into the decision tool. None of
these were "fixed" by guessing — the tool uses the documents as written and
flags the affected outputs.

## Inconsistencies in the project documents

| Document | Issue | Effect in the tool |
|---|---|---|
| BOM & cost doc / Master Report Table 3 | Consumables high total stated as ₹38,850 per m²; the 16 rows add up to **₹42,850** (₹4,000 slip). The 6-panel figure ₹2,33,100 inherits it (rows give ₹2,57,100). | The estimator adds the rows. |
| BOM & cost doc / Master Report Table 5 | **Mild steel mould ₹3k–13k** is 10–100× below aluminium (₹1–3L) and Invar (₹3–8L); likely ₹3L–13L. Table 6's aerospace scenario uses the low figure. | Kept as given, flagged UNVERIFIED in every report. It makes mild steel win the prototype and production profiles on cost — **confirm this number**. |
| Master Report Table 6 | Low-cost moulds "₹70,000–2,80,000" for MDF/PU + aluminium do not match Table 5 (MDF ₹20–50k or PU ₹50k–1L, + aluminium ₹1–3L). Mid-range ₹2,00,000–5,30,000 vs rows ₹2,00,000–5,50,000. | The estimator uses Table 5 rows (low-cost = PU board + aluminium). |
| Master Report Table 1 vs HexPly M18/1 datasheet | DOE cure-pressure levels "4 bar vs 6 bar", but the study article is a honeycomb **sandwich** panel and the M18/1 sandwich cycle is limited to **2 bar** to avoid core crush. | DOE runs above 2 bar on a sandwich panel carry a core-crush warning; choose levels within the prepreg's sandwich range or vary pressure on monolithic coupons. |
| BOM & cost doc | Mould BOM rows 3, 5, 6, 7, 12 (CNC machining, polishing, tooling resin, reinforcement, inspection) have no cost. | Not included in mould cost. |

## Data gaps (cells left empty rather than invented)

| Gap | Where | Needed from |
|---|---|---|
| Specific heat & conductivity of CFRP tooling, graphite, tooling boards | `tooling_data/tool_materials.csv` | Supplier TDS (Hexcel HexTool, GrafTech, RAMPF, General Plastics) — enables thermal lag for these tools |
| HexTool M61 cured density | same | Hexcel (an analogue 1580 kg/m³ is used and flagged) |
| Graphite and FR-4800 cycle life, ₹ cost, graphite max temperature in air | same | Supplier quotes |
| Electroformed-nickel data | same | Supplier electroform data (wrought Nickel 200 is a proxy) |
| MDF and PU tooling board properties | not modelled | CTE, density, max temperature — then add rows |
| Cooling rates of the M18/1 cycles | `process_data/cure_cycles.csv` | Datasheet says "controlled rate"; 2 °C/min assumed and flagged |
| NCAMP 8552 cure cycle "M" (NPS 81228) steps | not included | NCAMP process specification |
| Lamina data for T1100-class fibers (> 6826 MPa) | `literature_data/` | Published lamina tests; estimates are withheld until then |
| Real ground truth for fiber weights | `expert_ratings_template.csv`, `Simulation_Results_v1.csv` | Expert ratings or the 85 planned DOE simulations |
