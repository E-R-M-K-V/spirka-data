# Spirka data

Nightly timetable data for the Sofia public transport page (ermkv.world/bulgaria/sofia-public-transport/).

- Every night `scripts/nightly.sh` downloads the official GTFS timetable of the Sofia Urban Mobility Center,
  builds `v1/index.json` and one small file per stop in `v1/stops/`, and publishes them on the `gh-pages` branch.
- The page reads them from `https://<your-user-name>.github.io/spirka-data/v1/`.
- Last night's data stays available in `v1.prev/`.
- If the city's file looks broken (too few stops, known stops missing), nothing is published and GitHub emails you.

Data: Sofia Urban Mobility Center, open GTFS data, CC BY 4.0. Unofficial.
