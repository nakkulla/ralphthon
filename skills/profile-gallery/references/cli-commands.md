# pgal CLI Commands

Default API URL: `PGAL_API_URL` or `http://localhost:8000`.

Machine-readable output uses `--json`. JSON input uses `--data <file|->`.

```bash
pgal profile create --data profile.json --json
pgal profile create --data - --json
pgal profile get <profile_id> --json
pgal profile list --json
pgal profile update <profile_id> --data patch.json --json
pgal profile delete <profile_id> --json

pgal image add <profile_id> --file image.png --prompt "prompt" --request-id <request_id> --json
pgal image list <profile_id> --json
pgal image delete <image_id> --json

pgal tag add <profile_id> --tags music,ai --keywords waveform --json
pgal tag remove <profile_id> --tags music --json
pgal tag list --json

pgal search --q "music ai" --tags music --tech FastAPI,pgvector --tech-match all --json
```
