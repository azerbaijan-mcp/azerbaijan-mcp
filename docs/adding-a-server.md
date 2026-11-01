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
5. Fill in the source checklist from [data-policy.md](data-policy.md) in the server's issue.
6. Write the package README: tools, install, and a **Data source and terms** section with the
   checklist answers. Put the registry marker on the first line:
   `<!-- mcp-name: io.github.azerbaijan-mcp/<source> -->`.
7. Copy `server.json` from `packages/cbar` and change the name, description, `subfolder`,
   identifier and versions. `python scripts/release.py check` fails if it disagrees with
   `pyproject.toml` or the README marker.
8. Add the server to the table in the root README. CI picks up every package under `packages/`.
9. Before the first release add a PyPI trusted publisher for the new package (see
   [releasing.md](releasing.md)).

Rules for every server: read-only tools, no personal data, honest User-Agent, official data first.
