import sqlite3
from contextlib import contextmanager
from threading import Lock
import pandas as pd
import config
from typing import Dict, Union


class SQLiteConnectionPool:
    """
    Initialize the object with a database and a maximum number of connections.

    Args:
        database (str): The database to connect to.
        max_connections (int): The maximum number of connections allowed.
    """

    def __init__(self, database: str, max_connections: int = 5):
        self.database = database
        self.max_connections = max_connections
        self.connections = []
        self.lock = Lock()

    def get_connection(self):
        """
        Get a connection from the pool.

        Returns:
            sqlite3.Connection: A connection from the pool.
        """

        with self.lock:
            if self.connections:
                return self.connections.pop()
            else:
                return sqlite3.connect(self.database)

    def return_connection(self, connection):
        """
        Return a connection to the pool.

        Args:
            connection (sqlite3.Connection): The connection to return.

        Returns:
            None
        """

        with self.lock:
            if len(self.connections) < self.max_connections:
                self.connections.append(connection)
            else:
                connection.close()

    @contextmanager
    def connection(self):
        """
        A context manager that yields a connection from the pool.
        """

        conn = self.get_connection()
        try:
            yield conn
        finally:
            self.return_connection(conn)


def create_sql_db_from_csv(
        csv_path: str, db_path: str = "ec2.db", table_name: str = "ec2_rec"
):
    """
    Create a SQLite database from a CSV file.

    Args:
        csv_path (str): The file path to the CSV file.
        db_path (str): The file path to the SQLite database (default is "ec2.db").
        table_name (str): The name of the table to be created in the database (default is "ec2_rec").

    Returns:
        None
    """

    conn = sqlite3.connect(db_path)
    df = pd.read_csv(csv_path)
    df.to_sql(table_name, conn, if_exists="replace", index=False)


def find_best_instance(
        cpu: int = config.DEFAULT_CPU, ram: float = config.DEFAULT_RAM
) -> Dict[str, Union[str, bool]]:
    """
    Find the best instance based on CPU and RAM requirements.
    Assumption - inputs in GB

    For example here - setting defaults for CPU and RAM. This is to account for case where user specifies only one of them.
    This could be easily modified if don't want defaults and require both from user

    Given business case of problem is to determine optimal infrastructure for EC2 while being extensible to other deployment types,
    Text2SQL approach seems overboard in current state as much more prone to error.

    Args:
        cpu (int): The CPU requirement in vCPUs.
        ram (float): The RAM requirement in GB.

    Returns:
        Dict[str, Union[str, bool]: A dictionary containing the best instance details.
    """

    query = """
    SELECT *
    FROM ec2_rec
    WHERE vCPUs >= ? AND Instance_Memory >= ? AND On_Demand IS NOT NULL
    ORDER BY On_Demand ASC
    LIMIT 1
    """

    # AND GPU >= ? - doesn't exist in sample table found online

    try:
        with config.sql_ec2_connection_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (cpu, ram))
            row = cursor.fetchone()
            if row:
                columns = [column[0] for column in cursor.description]
                result = dict(zip(columns, row))
                result["found"] = True
            else:
                result = {
                    "found": False,
                    "message": f"No instance found with CPU >= {cpu}, RAM >= {ram}",
                }
            return result

    except sqlite3.Error as e:
        return {"found": False, "message": f"Database error occurred: {str(e)}"}
