"""
Build literature_data/lamina_calibration_data.csv from cited sources.

Every number below is transcribed from the named document; nothing is
estimated. NCAMP values are RTD (room-temperature dry) means, normalized
to the report's nominal cured ply thickness, converted from ksi/Msi to SI.
Hexcel rows are read from the repo's Hexcel_HexTow_Carbon_Fiber_Database_v2.csv
(HexTow datasheets, HexPly 8552 composite properties).
"""
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
KSI_TO_MPA = 6.894757
MSI_TO_GPA = 6.894757

rows = []

# --- NCAMP measured qualification data (independent test lab) ---
NCAMP = [
    # fiber_id, product, resin, Xt ksi, E1 Msi, Xc ksi, SBS ksi, Vf method I/II, report, url, table
    ("HEX-015", "HexTow IM7", "Hexcel 8552", 362.69, 22.99, 248.94, 17.13, (58.535, 59.405),
     "NCAMP CAM-RP-2009-015 Rev B (2019), Hexcel 8552 IM7 Unidirectional",
     "https://www.wichita.edu/industry_and_defense/NIAR/Documents/Qual-CAM-RP-2009-015-Rev-B-Hexcel-8552-IM7-MPDR-04.16.19.pdf",
     "Table 2-1, p.28"),
    ("HEX-002", "HexTow AS4", "Hexcel 8552", 289.47, 18.46, 202.70, 16.63, (59.716, 58.733),
     "NCAMP CAM-RP-2010-002 Rev A (2011), Hexcel 8552 AS4 Unidirectional",
     "https://www.wichita.edu/industry_and_defense/NIAR/Research/hexcel-8552/AS4-Unitape-2.pdf",
     "Table 2-1, p.30"),
]
for fid, prod, resin, xt, e1, xc, sbs, vf, ref, url, tab in NCAMP:
    rows.append({
        "source_type": "NCAMP_measured", "fiber_id": fid, "fiber_product": prod, "resin": resin,
        "lamina_tensile_strength_mpa": round(xt * KSI_TO_MPA, 1),
        "lamina_tensile_modulus_gpa": round(e1 * MSI_TO_GPA, 1),
        "lamina_compressive_strength_mpa": round(xc * KSI_TO_MPA, 1),
        "lamina_sbs_or_ilss_mpa": round(sbs * KSI_TO_MPA, 1),
        "fiber_volume_percent": round(sum(vf) / 2, 2),
        "normalization": "normalized to nominal CPT; RTD mean",
        "notes": "F1cu derived from cross-ply via back-out factor; SBS is the measured value",
        "source_document": ref, "source_url": url, "source_location": tab,
    })

# --- MIL-HDBK-17-2F (CMH-17) Vol. 2, measured lamina data (project folder) ---
# Room-temperature ambient means, normalized to 60 % fiber volume, 0° tension.
MILHDBK = [
    # fiber_id, product, resin, table, F1tu ksi, E1t Msi, data class, note
    ("HEX-002", "HexTow AS4", "Hercules/Fiberite E7K8 epoxy", "4.2.3(a)", 303, 19.3, "Screening", ""),
    ("HEX-002", "HexTow AS4", "Fiberite 938 epoxy", "4.2.5(a)", 314, 22.4, "Interim",
     "normalized E1t is above the rule-of-mixtures bound for AS4 - verify"),
    ("HEX-002", "HexTow AS4", "Hercules 3502 epoxy", "4.2.8(a)", 258, 19.3, "B30", ""),
    ("HEX-002", "HexTow AS4", "Hercules 3501-6 epoxy (bleed)", "4.2.12(a)", 291, 19.6, "Interim", ""),
    ("HEX-002", "HexTow AS4", "Hercules 3501-6 epoxy (no bleed)", "4.2.13(a)", 290, 18.9, "Interim", ""),
    ("TOR-T300", "T300", "Fiberite 976 epoxy (T300 15k)", "4.2.17(a)", 211, 19.6, "Screening", ""),
    ("HEX-002", "HexTow AS4", "Fiberite 997 epoxy", "4.2.28(a)", 327, 19.9, "B30", ""),
    ("TOR-T300", "T300", "F650 BMI (T-300 3k)", "4.4.1(a)", 248, 18.9, "Screening", ""),
    ("HEX-002", "HexTow AS4", "5250-3 BMI", "4.4.4(a)", 252, 15.9, "Screening", ""),
    ("HEX-014", "HexTow IM6", "APC-2 PEEK (thermoplastic)", "4.9.1(a)", 350, 21.6, "Screening", ""),
    ("TOR-M55J", "M55J", "954-3 cyanate ester", "4.10.1(a)", 324, 47.7, "A55", ""),
]
for fid, prod, resin, table, xt, e1, cls, note in MILHDBK:
    rows.append({
        "source_type": "MIL-HDBK-17_measured", "fiber_id": fid, "fiber_product": prod, "resin": resin,
        "lamina_tensile_strength_mpa": round(xt * KSI_TO_MPA, 1),
        "lamina_tensile_modulus_gpa": round(e1 * MSI_TO_GPA, 1),
        "lamina_compressive_strength_mpa": None, "lamina_sbs_or_ilss_mpa": None,
        "fiber_volume_percent": 60.0,
        "normalization": "normalized to 60% fiber volume; RT ambient mean",
        "notes": f"data class {cls}" + (f"; {note}" if note else ""),
        "source_document": "MIL-HDBK-17-2F Vol. 2 (2002)",
        "source_url": "", "source_location": f"Table {table}",
    })

# --- Toray manufacturer datasheets (normalized to 60% Vf, epoxy cured 130 C) ---
TORAY = [
    ("TOR-T300", "T300", "#2500 epoxy", 1820, 140, 1470, 94.1, "T300-Data-Sheet.pdf"),
    ("TOR-T700S", "T700S", "epoxy (unnamed)", 2860, 134, 1450, 86.9, "T700S-Data-Sheet.pdf"),
    ("TOR-T700G", "T700G", "#2500 epoxy", 2040, 141, 1645, 102.1, "T700G-Data-Sheet.pdf"),
    ("TOR-T800S", "T800S", "#2592 epoxy", 3290, 163, 1490, 87.9, "T800S-Data-Sheet.pdf"),
]
for fid, prod, resin, xt, e1, xc, ilss, doc in TORAY:
    rows.append({
        "source_type": "manufacturer_datasheet", "fiber_id": fid, "fiber_product": prod, "resin": resin,
        "lamina_tensile_strength_mpa": xt, "lamina_tensile_modulus_gpa": e1,
        "lamina_compressive_strength_mpa": xc, "lamina_sbs_or_ilss_mpa": ilss,
        "fiber_volume_percent": 60.0, "normalization": "normalized to 60% fiber volume",
        "notes": "ILSS per SACMA SRM; compression per SACMA SRM 1R-94",
        "source_document": f"Toray Composite Materials America, {doc}",
        "source_url": f"https://www.toraycma.com/wp-content/uploads/{doc}",
        "source_location": "Composite Properties table",
    })

# --- Hexcel HexTow datasheets (already transcribed in the repo) ---
hex_db = pd.read_csv(HERE.parent / "Hexcel_HexTow_Carbon_Fiber_Database_v2.csv")
fiber_db = pd.read_csv(HERE.parent / "Carbon_Fiber_Master_v6_Top5(1).csv")
id_by_product = dict(zip(fiber_db["product"], fiber_db["fiber_id"]))
for _, r in hex_db.dropna(subset=["Composite_0deg_Tensile_Strength_MPa"]).iterrows():
    rows.append({
        "source_type": "manufacturer_datasheet",
        "fiber_id": id_by_product.get(r["Product"], ""), "fiber_product": r["Product"],
        "resin": r["Composite_System"],
        "lamina_tensile_strength_mpa": r["Composite_0deg_Tensile_Strength_MPa"],
        "lamina_tensile_modulus_gpa": r["Composite_0deg_Tensile_Modulus_GPa"],
        "lamina_compressive_strength_mpa": r["Composite_0deg_Compressive_Strength_MPa"],
        "lamina_sbs_or_ilss_mpa": r["Composite_SBS_MPa"],
        "fiber_volume_percent": r.get("Fiber_Volume_percent"),
        "normalization": "as stated on HexTow datasheet",
        "notes": "transcribed in Hexcel_HexTow_Carbon_Fiber_Database_v2.csv",
        "source_document": f"Hexcel HexTow datasheet ({r['Source_File']})",
        "source_url": "", "source_location": "Typical HexPly 8552 composite properties",
    })

out = pd.DataFrame(rows)
missing = out[out["fiber_id"] == ""]
if not missing.empty:
    raise SystemExit(f"Unmatched fiber products: {missing['fiber_product'].tolist()}")
out.to_csv(HERE / "lamina_calibration_data.csv", index=False)
print(f"Wrote {len(out)} rows: {out['source_type'].value_counts().to_dict()}")
