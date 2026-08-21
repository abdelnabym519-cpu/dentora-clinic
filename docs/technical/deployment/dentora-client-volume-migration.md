# Dentora client persistent-volume migration

`docker-compose.client.yml` gives new installations Dentora-only physical
volume names. It must not be used by itself to switch an installation that
already has clinic data under different physical volume names.

## Existing installation procedure

1. Inspect the running PostgreSQL, storage, and Caddy mounts. Record their
   physical volume names, PostgreSQL row counts, media count, installation ID,
   and license state.
2. Back up the clinic using the supplied backup procedure. Do not remove any
   Docker volume.
3. Set the recorded physical names only in the untracked `.env.client`:

   ```dotenv
   DENTORA_POSTGRES_VOLUME=<inspected-postgres-volume>
   DENTORA_STORAGE_VOLUME=<inspected-storage-volume>
   DENTORA_CADDY_DATA_VOLUME=<inspected-caddy-data-volume>
   DENTORA_CADDY_CONFIG_VOLUME=<inspected-caddy-config-volume>
   ```

4. Validate the resolved configuration before switching services:

   ```sh
   docker compose -f docker-compose.client.yml \
     -f docker-compose.client.existing-volumes.yml config
   ```

5. Use the existing-volumes overlay only after the output identifies all four
   volumes as external. It never creates or removes a volume.
6. After start-up, verify the recorded row counts, media count,
   `/app/storage/license/installation_id.txt`, and local license state before
   accepting the migration.

Never use a `-v` shutdown, a volume prune, or a database reset as part of this
procedure. The database name remains `dental_clinic`; no database or Alembic
reset is required for the Dentora rebrand.
