# ⚽ Football Shuffler

Professional pickup football team generator, balancer, and "Winner Stays On" pitch queue manager with cloud sync powered by FastAPI and MySQL.

## Features
- **Fair Tier Balancing**: Shuffles and deals players tier-by-tier with random tie-breakers.
- **Top-Tier Team Naming**: Automatically names each squad after their Tier 1 captain (e.g. *Team Messi*).
- **Match Arena**: "Winner stays on" pitch flow with match counter and bench queue.
- **Goalkeeper Selection**: Random keeper assignment (`🧤`) with instant re-roll.
- **Account Registration & Cloud Sync**: User registration/login backed by MySQL and FastAPI.

## Tech Stack
- **Frontend**: Vanilla HTML5, CSS3, JavaScript (Mobile-first, dark/light theme).
- **Backend**: FastAPI, SQLAlchemy, PyMySQL, Passlib, Python-Jose.
- **Database**: MySQL (Aiven Cloud / PlanetScale / Railway).
- **Deployment**: Vercel.
