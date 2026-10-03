"""Offline example using synthetic data and a temporary SQLite database."""
from pathlib import Path
from tempfile import TemporaryDirectory

from researchos.db import create_db_engine, init_db, repository
from sqlalchemy.orm import sessionmaker


def main():
    with TemporaryDirectory(prefix="researchos_example_") as directory:
        url = "sqlite:///" + (Path(directory) / "example.db").as_posix()
        init_db(url)
        engine = create_db_engine(url)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            with factory.begin() as session:
                project = repository.create_project(session, title="Synthetic ResearchOS example")
                project_id = project.id
            with factory() as session:
                print(repository.get_project(session, project_id).title)
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
