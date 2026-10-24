# Checking GeoSpark's datum and height answers against the agencies

GeoSpark's `transform_coordinates` and `convert_height` use PROJ, so agreeing with PROJ proves nothing
on its own. These checks compare GeoSpark with each national agency's own published service or test
data. Run on 2026-10-24 with GeoSpark at `main` after #42, PROJ 9.8.1, EPSG v12.029.

| Agency | What was compared | Points | Largest difference |
|---|---|---|---|
| Geoscience Australia, [Geodetic Calculators API](https://geodesyapps.ga.gov.au/api-docs/index.html) | GDA94 to GDA2020 | 8 (Melbourne, Hobart, Sydney, Perth, Darwin, Cairns, Alice Springs, UniMelb) | 0.07 mm |
| Geoscience Australia, same API | ATRF2014 at 19 Oct 2026 to GDA2020 (GeoSpark given ITRF2014) | 4 | 0.11 mm |
| Geoscience Australia, [AUSGeoid2020 calculator](https://geodesyapps.ga.gov.au/ausgeoid2020) | Ellipsoidal height to AHD | 3 (Melbourne 35.257, Perth 72.541, Sydney 37.339) | 2 mm |
| Ordnance Survey, OSTN15/OSGM15 developer pack test files | ETRS89 to British National Grid | 40 | 7.8 mm (mean 1.9 mm) |
| Ordnance Survey, same | Ellipsoidal height to OSGM15 height | 39 (Scilly refused, see below) | 2.0 mm (mean 0.6 mm) |
| Ordnance Survey, same | Which local datum OSGM15 heights are in | 40 | all match OS's datum flags |
| LINZ, [height transformation example points](https://www.linz.govt.nz/node/6605) | NZGD2000 to NZVD2016 | 2 | 4.7 mm (LINZ rounds to 0.01 m) |
| NOAA NGS, [GEOID18 service](https://geodesy.noaa.gov/api/geoid/ght) | Ellipsoidal height to NAVD88 | 2 (San Francisco, Denver) | 1 mm |
| NOAA NGS, [NCAT](https://geodesy.noaa.gov/api/ncat/llh) (NADCON 5) | NAD27 to NAD83 | 1 (San Francisco) | **0.27 m**: PROJ uses the original NADCON; NGS states ±0.27 m there |

What this changed in GeoSpark:

- **AHD** is refused outside mainland Australia and Tasmania. The AUSGeoid2020 grid extends over the
  sea and to external territories, but GA's calculator says the model is valid onshore only.
- **OSGM15** heights on Scilly, the Isle of Man, the Outer Hebrides, Orkney and Shetland are in local
  datums (St Marys, Douglas02, Stornoway15, Newlyn (Orkney), Lerwick), not ODN; GeoSpark now labels
  them so, and says that heights more than 2 km offshore are in "Newlyn Offshore". The Scilly test
  point is refused for ODN (PROJ's ODN operation doesn't cover it).
- **NZVD2016** is refused for the Chatham Islands: the NZGeoid2016 grid file on the PROJ CDN stops at
  180 degrees, although EPSG's area of use is wider.
- **NAD27 to NAD83** is reported with its operation (original NADCON), and the 0.27 m difference from
  NADCON 5 is stated in the README.

The OS test files are not redistributed here; they are in Ordnance Survey's free
[OSTN15/OSGM15 developer pack](https://www.ordnancesurvey.co.uk/products/os-net/for-developers).
