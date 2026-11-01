# Adding a server

1. Copy `packages/cbar` to `packages/<source>` (for example `packages/opendata`).
2. Rename the distribution to `azerbaijan-mcp-<source>`, the module to `azerbaijan_mcp_<source>` and
   the console script to `azerbaijan-mcp-<source>`.
3. Keep the layout:
   - `client.py`: fetch and parse, no MCP imports.
   - `server.py`: tools only, with `create_server(client=None)` so tests can inject a fake client.
   - `tests/`: a saved fixture of the real upstream response.
4. Tests run offline by default (fixtures plus `httpx.MockTransport`). Add one `@pytest.mark.live`
   contract test against the real upstream so format changes show up.
5. Write the package README: tools, install, and a **Data source and terms** section (who publishes
   the data, licence or terms status, rate limits).
6. Add the server to the table in the root README. CI picks up every package under `packages/`.

Rules for every server: read-only tools, no personal data, honest User-Agent, official data first.
