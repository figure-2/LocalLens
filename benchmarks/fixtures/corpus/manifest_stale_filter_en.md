LocalLens validates search results against the manifest before returning them.
The store keeps named text and vision vectors, while the manifest decides whether a unit is still current.
This avoids serving stale evidence after a file changes or disappears.
