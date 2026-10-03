# Examples

After the root editable installation, run `python examples/local_project.py`. It creates a synthetic project, reads it back, prints its title, and removes the temporary database. No API calls or credentials are needed.

For the dashboard, run `npm run e2e:api` from `apps/dashboard/frontend` and run `npm run dev -- --host 127.0.0.1` in a second terminal there. The API seeder uses temporary synthetic records, including illustrative metrics and claims; these are UI fixtures, not scientific results. Stop both servers after inspection. Abrupt process termination can leave temporary files in the operating system's temporary directory.
