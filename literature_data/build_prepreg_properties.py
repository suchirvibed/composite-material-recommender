"""
Build literature_data/prepreg_laminate_properties.csv — cured-laminate
properties for the prepregs in Prepreg_Master_Database_v2_Expanded.csv.

The prepreg master database identifies each system but carries almost no
mechanical data, so selecting a prepreg by strength needs the cured-laminate
values from each system's datasheet. Every value below is transcribed from
the named datasheet table (units as stated there, converted where marked);
a prepreg with no published laminate data is NOT given a guessed value — it
is listed as "datasheet needed" by prepreg_selector.py.

One prepreg system can be sold with several fibers (M21, M56): each published
fiber variant is its own row, tied to the master row by `prepreg_id`.

Run:  py literature_data/build_prepreg_properties.py
"""

from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
KSI = 6.894757           # ksi → MPa
MSI = 6.894757           # Msi → GPa

COLUMNS = ["variant_id", "prepreg_id", "variant", "fiber", "form", "tensile_strength_mpa",
           "tensile_modulus_gpa", "fiber_volume_percent", "laminate_density_g_cm3",
           "density_basis", "cured_ply_mm", "tg_dry_C", "test_condition", "normalization",
           "source_document", "source_location", "source_url", "notes"]

ROWS = [
    # HexPly 8552 EU datasheet — Prepreg Properties, UD carbon (25 °C dry)
    dict(variant_id="8552_AS4_UD", prepreg_id="HXC_8552_AS4_12K_35RC", variant="8552/35%/134/AS4",
         fiber="AS4 12K", form="UD", tensile_strength_mpa=2207, tensile_modulus_gpa=141,
         fiber_volume_percent=57.42, laminate_density_g_cm3=1.58, density_basis="datasheet",
         cured_ply_mm=0.130, tg_dry_C=200, test_condition="25 °C dry",
         normalization="as stated in datasheet",
         source_document="Hexcel HexPly 8552 product data sheet (EU)",
         source_location="Prepreg Properties — Mechanical Properties, AS4 column",
         source_url="https://energy.ornl.gov/CFCrush/materials/uou/8552_eu.pdf",
         notes="NCAMP measured RTD mean 1996 MPa / 127 GPa (CAM-RP-2010-002) - independent tests run ~7 % lower"),
    dict(variant_id="8552_IM7_UD", prepreg_id="HXC_8552_IM7_12K_35RC", variant="8552/35%/134/IM7",
         fiber="IM7 12K", form="UD", tensile_strength_mpa=2724, tensile_modulus_gpa=164,
         fiber_volume_percent=57.70, laminate_density_g_cm3=1.57, density_basis="datasheet",
         cured_ply_mm=0.131, tg_dry_C=200, test_condition="25 °C dry",
         normalization="as stated in datasheet",
         source_document="Hexcel HexPly 8552 product data sheet (EU)",
         source_location="Prepreg Properties — Mechanical Properties, IM7 column",
         source_url="https://energy.ornl.gov/CFCrush/materials/uou/8552_eu.pdf",
         notes="NCAMP measured RTD mean 2501 MPa / 158 GPa (CAM-RP-2009-015) - independent tests run ~9 % lower"),
    # Toray 3900 prepreg system data sheet
    dict(variant_id="3900_T800S_UD", prepreg_id="TCA_3900_P2362W_19L", variant="P2362W-19L (AMS 6891/1)",
         fiber="T800S 24K", form="UD", tensile_strength_mpa=round(436 * KSI), tensile_modulus_gpa=round(21.5 * MSI),
         fiber_volume_percent="", laminate_density_g_cm3=1.54, density_basis="datasheet",
         cured_ply_mm=0.191, tg_dry_C=204, test_condition="RTA 72 °F (22 °C), ambient",
         normalization="normalized to the stated CPT",
         source_document="Toray 3900 Prepreg System data sheet",
         source_location="Lamina/laminate mechanical properties: P2362W-19L (T800S-24K UD), RTA column",
         source_url="https://www.toraycma.com/wp-content/uploads/3900-Prepreg-System.pdf",
         notes="436 ksi / 21.5 Msi as printed"),
    dict(variant_id="3900_T830H_PW", prepreg_id="TCA_3900_FM6673G_37KL", variant="FM6673G-37KL",
         fiber="T830H 6K", form="plain weave", tensile_strength_mpa=round(150 * KSI), tensile_modulus_gpa=round(10.0 * MSI),
         fiber_volume_percent="", laminate_density_g_cm3=1.51, density_basis="datasheet",
         cured_ply_mm="", tg_dry_C=204, test_condition="RTA 72 °F (22 °C), ambient, warp",
         normalization="normalized to the stated CPT",
         source_document="Toray 3900 Prepreg System data sheet",
         source_location="Lamina/laminate mechanical properties: FM6673G-37KL (T830H-6K PW), RTA column",
         source_url="https://www.toraycma.com/wp-content/uploads/3900-Prepreg-System.pdf",
         notes="150 ksi / 10.0 Msi as printed; woven, so 0° strength is about half of UD"),
    # HexPly M21 global datasheet — Cured Unidirectional Prepreg Properties, M21/34%/UD194
    dict(variant_id="M21_IM7_UD", prepreg_id="HXC_M21", variant="M21/34%/UD194/IM7-12K",
         fiber="IM7 12K", form="UD", tensile_strength_mpa=2860, tensile_modulus_gpa=160,
         fiber_volume_percent=59.2, laminate_density_g_cm3=1.58, density_basis="datasheet (theoretical)",
         cured_ply_mm=0.184, tg_dry_C=195, test_condition="23 °C",
         normalization="as stated in datasheet (US standards column)",
         source_document="Hexcel HexPly M21 product data sheet (global)",
         source_location="Cured Unidirectional Prepreg Properties, IM7-12K column",
         source_url="https://hexcel.com/wp-content/uploads/2025/12/HexPly_M21_global_DataSheet.pdf", notes=""),
    dict(variant_id="M21_AS7_UD", prepreg_id="HXC_M21", variant="M21/34%/UD194/AS7-12K",
         fiber="AS7 12K", form="UD", tensile_strength_mpa=2350, tensile_modulus_gpa=148,
         fiber_volume_percent=58.9, laminate_density_g_cm3=1.58, density_basis="datasheet (theoretical)",
         cured_ply_mm=0.184, tg_dry_C=195, test_condition="23 °C",
         normalization="as stated in datasheet (European standards column)",
         source_document="Hexcel HexPly M21 product data sheet (global)",
         source_location="Cured Unidirectional Prepreg Properties, AS7-12K column",
         source_url="https://hexcel.com/wp-content/uploads/2025/12/HexPly_M21_global_DataSheet.pdf", notes=""),
    dict(variant_id="M21_IMA_UD", prepreg_id="HXC_M21", variant="M21/34%/UD194/IMA-12K",
         fiber="IMA 12K", form="UD", tensile_strength_mpa=3050, tensile_modulus_gpa=178,
         fiber_volume_percent=59.2, laminate_density_g_cm3=1.58, density_basis="datasheet (theoretical)",
         cured_ply_mm=0.184, tg_dry_C=195, test_condition="23 °C",
         normalization="as stated in datasheet (European standards column)",
         source_document="Hexcel HexPly M21 product data sheet (global)",
         source_location="Cured Unidirectional Prepreg Properties, IMA-12K column",
         source_url="https://hexcel.com/wp-content/uploads/2025/12/HexPly_M21_global_DataSheet.pdf", notes=""),
    # HexPly M56 global datasheet — Cured Prepreg Properties (continued), UD carbon normalized to 60 % Vf
    dict(variant_id="M56_IM7_UD", prepreg_id="HXC_M56", variant="M56/35%/UD268/IM7-12K",
         fiber="IM7 12K", form="UD", tensile_strength_mpa=2730, tensile_modulus_gpa=182,
         fiber_volume_percent=58.8, laminate_density_g_cm3=1.53, density_basis="datasheet (theoretical)",
         cured_ply_mm=0.253, tg_dry_C=204, test_condition="room temperature, oven cure 180 °C",
         normalization="tension normalized to Vf = 60 % (UD carbon)",
         source_document="Hexcel HexPly M56 product data sheet (global)",
         source_location="Cured Prepreg Properties (continued), IM7-12K column",
         source_url="https://hexcel.com/wp-content/uploads/2026/01/HexPly_M56_global_DataSheet.pdf", notes=""),
    dict(variant_id="M56_AS7_UD", prepreg_id="HXC_M56", variant="M56/35%/UD134/AS7-12K",
         fiber="AS7 12K", form="UD", tensile_strength_mpa=2330, tensile_modulus_gpa=141,
         fiber_volume_percent=56.2, laminate_density_g_cm3=1.53, density_basis="datasheet (theoretical)",
         cured_ply_mm=0.134, tg_dry_C=197, test_condition="room temperature, oven cure 180 °C",
         normalization="tension normalized to Vf = 60 % (UD carbon)",
         source_document="Hexcel HexPly M56 product data sheet (global)",
         source_location="Cured Prepreg Properties (continued), AS7-12K column",
         source_url="https://hexcel.com/wp-content/uploads/2026/01/HexPly_M56_global_DataSheet.pdf", notes=""),
    # HexPly M18/1 — project datasheet guide (55 % Vf, RT dry); density by rule of mixtures
    dict(variant_id="M18-1_G947_UD", prepreg_id="HXC_M18_1", variant="M18/1 + G947 UD",
         fiber="carbon (G947)", form="UD", tensile_strength_mpa=1750, tensile_modulus_gpa=128,
         fiber_volume_percent=55, laminate_density_g_cm3=round(0.55 * 1.78 + 0.45 * 1.22, 3),
         density_basis="ANALYTICAL: rule of mixtures, fiber 1.78 + resin 1.22 g/cm³ at 55 % Vf",
         cured_ply_mm=0.165, tg_dry_C=200, test_condition="RT dry",
         normalization="55 % fiber volume",
         source_document="HexPly M18/1 datasheet guide (project folder)",
         source_location="4. Mechanical properties — UD 0° tensile",
         source_url="", notes="Service temperature 135 °C wet"),
    dict(variant_id="M18-1_G939_FABRIC", prepreg_id="HXC_M18_1", variant="M18/1 + G939 fabric",
         fiber="carbon (G939)", form="fabric", tensile_strength_mpa=800, tensile_modulus_gpa=65,
         fiber_volume_percent=55, laminate_density_g_cm3=round(0.55 * 1.78 + 0.45 * 1.22, 3),
         density_basis="ANALYTICAL: rule of mixtures, fiber 1.78 + resin 1.22 g/cm³ at 55 % Vf",
         cured_ply_mm=0.227, tg_dry_C=200, test_condition="RT dry",
         normalization="55 % fiber volume",
         source_document="HexPly M18/1 datasheet guide (project folder)",
         source_location="4. Mechanical properties — woven 0° tensile",
         source_url="", notes="Balanced fabric: 800 MPa both ways"),
]


def main():
    with open(HERE / "prepreg_laminate_properties.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(ROWS)
    print(f"Wrote {len(ROWS)} prepreg laminate variants.")


if __name__ == "__main__":
    main()
