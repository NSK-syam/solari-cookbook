# Citation appendix

## Product evidence

- Mireye hosted MCP and product documentation: <https://www.mireye.com/>
- Delaware permitted septic systems dataset: <https://data.delaware.gov/Energy-and-Environment/Permitted-Septic-Systems/mv7j-tx3u>
- NOAA National Weather Service API: <https://www.weather.gov/documentation/services-web-api>
- EPA septic inspection guidance: <https://www.epa.gov/septic/frequent-questions-septic-systems>
- EPA maintenance, lifespan, and cost guidance: <https://www.epa.gov/septic/why-maintain-your-septic-system>
- USDA NRCS soil-survey use guidance: <https://www.nrcs.usda.gov/conservation-basics/soil/soil-surveys-can-help-you>

## Runtime provenance

Each evidence envelope stores a source name, source URL, retrieval timestamp, optional confidence, raw adapter payload, and request identifier where available. Each observed fact in a decision references citation identifiers from those envelopes. The memo renderer fails closed when a factual citation cannot be resolved.

Fixture citations identify the authoritative service and clearly label the response as recorded fixture evidence. Live mode preserves Mireye’s returned per-field provenance and direct public-source URLs.
