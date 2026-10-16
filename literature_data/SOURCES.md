# Literature data sources

Every value in this folder was transcribed from the documents below. Nothing
is estimated; where a value could not be read reliably it was left out.

## Measured lamina data (independent test lab)

| System | Report | Values used |
|---|---|---|
| Hexcel 8552 / IM7 UD | NCAMP CAM-RP-2009-015 Rev B, Wichita State NIAR, 2019 — [PDF](https://www.wichita.edu/industry_and_defense/NIAR/Documents/Qual-CAM-RP-2009-015-Rev-B-Hexcel-8552-IM7-MPDR-04.16.19.pdf) | Table 2-1 p.28, RTD normalized: F1tu 362.69 ksi, E1t 22.99 Msi, F1cu 248.94 ksi, SBS 17.13 ksi |
| Hexcel 8552 / AS4 UD | NCAMP CAM-RP-2010-002 Rev A, 2011 — [PDF](https://www.wichita.edu/industry_and_defense/NIAR/Research/hexcel-8552/AS4-Unitape-2.pdf) | Table 2-1 p.30, RTD normalized: F1tu 289.47 ksi, E1t 18.46 Msi, F1cu 202.70 ksi, SBS 16.63 ksi |
| Cytec 5320-1 / T650 UD | NCAMP CAM-RP-2013-002 Rev A, 2017 — [PDF](https://www.wichita.edu/industry_and_defense/NIAR/Research/cytec-5320-1/T650-Unitape-2.pdf) | **Not used**: T650 is not in the fiber database, and the compression columns of the summary table did not extract cleanly. RTD F1tu 299.09 ksi / E1t 20.08 Msi kept here for reference. |

F1cu in both NCAMP reports is derived from cross-ply tests via a back-out factor.

## Manufacturer datasheets (normalized to 60 % fiber volume)

- Toray CMA T300, T700S, T700G, T800S data sheets — `https://www.toraycma.com/wp-content/uploads/<grade>-Data-Sheet.pdf`
- Hexcel HexTow datasheets (AS4, AS4C, AS4D, AS7, IM6, IM7, IM8, IM10, IMA, PV40),
  HexPly 8552 composite properties — already transcribed in
  `Hexcel_HexTow_Carbon_Fiber_Database_v2.csv`

## MCDM weighting literature

- Kishore K. S., Subbaiah K. V. (2025). *Optimal Fiber Selection for Automobile Roof
  Top Application Using a Multi Criteria Decision-Making Framework.* RCMA.
  [doi:10.18280/rcma.350309](https://doi.org/10.18280/rcma.350309)
- Balakrishnan T. S. et al. (2022). *Selection of Natural Fibre for Pultruded Hybrid
  Synthetic/Natural Fibre Reinforced Polymer Composites Using Analytical Hierarchy
  Process for Structural Applications.* Polymers 14(15):3178.
  [doi:10.3390/polym14153178](https://doi.org/10.3390/polym14153178)

Rebuild the lamina CSV with `py literature_data/build_lamina_dataset.py`.
