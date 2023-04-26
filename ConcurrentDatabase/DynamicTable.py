import sqlite3
import typing

from .ColumnWrapper import ColumnWrapper
from .DynamicEntry import DynamicEntry


class DynamicTable:
    """
    A class that allows you to access a table in a database as if it were a dictionary.
    """

    def __init__(self, table_name, database):
        self.table_name = table_name
        self.database = database
        self.columns = []  # type: list[ColumnWrapper]
        self.entries = []  # type: list[DynamicEntry]
        self.primary_keys = []  # type: list[ColumnWrapper]
        self._load_columns()

    def _load_columns(self):
        sql = f"PRAGMA table_info({self.table_name})"  # Get the columns of the table
        result = self.database.get(sql)
        for row in result:
            column = ColumnWrapper(self, row)
            self.columns.append(column)

    def _validate_columns(self, **kwargs):
        """
        Validate that all columns are valid and that all constraints are met.
        :param kwargs: The columns to validate.
        :return: None
        :raises KeyError: If a column is not found in the table.
        """
        for column in kwargs:
            if column not in self.columns:
                raise KeyError(f"Column [{column}] not found in table [{self.table_name}]")
            actual_column = self.columns[self.columns.index(column)]
            actual_column.validate(kwargs[column])

    def _contains_primary_keys(self, **kwargs):
        """
        Validate that all primary keys are present in the kwargs
        :param kwargs:
        :return:
        """
        for primary_key in self.primary_keys:
            if primary_key.name not in kwargs:
                raise KeyError(f"Primary key [{primary_key.name}] not specified")

    def update_schema(self):
        """
        Update the schema of the table.
        :return: None
        """
        self.columns = []
        self._load_columns()

    def get_row(self, **kwargs) -> typing.Optional[DynamicEntry]:
        """
        Get a row from the table.
        :param kwargs: The filters to apply to the query.
        :return: The row.
        """
        self._validate_columns(**kwargs)
        self._contains_primary_keys(**kwargs)

        # Check if the DynamicEntry is already loaded
        for entry in self.entries:
            if entry == kwargs:
                return entry

        # Build the query
        sql = f"SELECT * FROM {self.table_name}"
        if len(kwargs) > 0:
            sql += " WHERE "
            for column in kwargs:
                sql += f"{column} = ? AND "
            sql = sql[:-5]
        result = self.database.get(sql, tuple(kwargs.values()))
        if result:
            return DynamicEntry(self, load_tuple=result[0])
        else:
            return None

    def get_rows(self, **kwargs) -> list[DynamicEntry]:
        """
        Get a set of rows from the table.
        :param kwargs: The filters to apply to the query.
        :return: The row.
        """
        # For each column validate that it is a valid column and that the constraints are met.
        self._validate_columns(**kwargs)

        # Build the query
        sql = f"SELECT * FROM {self.table_name}"
        if len(kwargs) > 0:
            sql += " WHERE "
            for column_name in kwargs:
                column = self.columns[self.columns.index(column_name)]
                sql += self._create_filter(column, kwargs[column]) + " AND "
            sql = sql[:-5]
        result = self.database.get(sql)
        if result:
            return [DynamicEntry(self, load_tuple=row) for row in result]
        else:
            return []

    def get_all(self) -> list[DynamicEntry]:
        """
        Get all rows from the table. This is not recommended for large tables.
        :return: The rows.
        """
        result = self.database.get(f"SELECT * FROM {self.table_name}")
        if result:
            return [DynamicEntry(self, load_tuple=row) for row in result]
        else:
            return []

    def add(self, **kwargs) -> DynamicEntry:
        """
        Add a row to the table.
        :param kwargs: The values of the entry
        :return: A DynamicEntry object representing the row.
        """
        # For each column validate that it is a valid column
        self._validate_columns(**kwargs)
        self._contains_primary_keys(**kwargs)

        # Build the query
        sql = f"INSERT INTO {self.table_name} ("
        for column in kwargs:
            sql += f"{column}, "
        sql = sql[:-2] + ") VALUES ("
        for column in kwargs:
            sql += "?, "
        sql = sql[:-2] + ")"
        try:
            self.database.run(sql, tuple(kwargs.values()))
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Integrity error: {e}")
        return DynamicEntry(self, **kwargs)

    def update_or_add(self, **kwargs) -> DynamicEntry:
        """
        Update a row if it exists, otherwise add it.
        :param kwargs: The values of the entry
        :return: A DynamicEntry object representing the row.
        """
        # For each column validate that it is a valid column
        self._validate_columns(**kwargs)
        self._contains_primary_keys(**kwargs)
        # Use get_row only on the primary keys included in the kwargs
        primary_keys = {key: kwargs[key] for key in kwargs if key in self.primary_keys}
        row = self.get_row(**primary_keys)
        if row:
            print(f"Updating row {row}")
            row.set(**kwargs)
            return row
        else:
            print("Adding row")
            return self.add(**kwargs)

    def delete(self, **kwargs):
        """
        Delete a row from the table.
        :param kwargs: The filters to apply to the query.
        :return: None
        """
        # For each column validate that it is a valid column and that the constraints are met.
        self._validate_columns(**kwargs)
        self._contains_primary_keys(**kwargs)

        # Build the query
        sql = f"DELETE FROM {self.table_name}"
        if len(kwargs) > 0:
            sql += " WHERE "
            for column in kwargs:
                sql += f"{column} = ? AND "
            sql = sql[:-5]
        self.database.run(sql, tuple(kwargs.values()))

    def delete_many(self, **kwargs):
        """
        Deletes rows with values matching the kwargs
        :param kwargs:
        :return:
        """
        # For each column validate that it is a valid column and that the constraints are met.
        self._validate_columns(**kwargs)

        if len(kwargs) == 0:
            raise ValueError("Must specify at least one column filter for delete_many")

        # Build the query
        sql = f"DELETE FROM {self.table_name}"
        if len(kwargs) > 0:
            sql += " WHERE "
            for column_name in kwargs:
                column = self.columns[self.columns.index(column_name)]
                sql += self._create_filter(column, kwargs[column]) + " AND "
            sql = sql[:-5]
        self.database.run(sql)

    def _create_filter(self, column, value):
        """
        Create an SQL filter from a kwargs key and value.
        :param key: The column name.
        :param value: The value to filter. value or [lower, upper] for ranges.
        :return:
        """
        if isinstance(value, list):
            if len(value) != 2:
                raise ValueError(f"Invalid range for column {column.name}")
            return f"{column.name} >= {column.safe_value(value[0])} AND {column.name} <= {column.safe_value(value[1])}"
        else:
            return f"{column.name} = {column.safe_value(value)}"

    def __getitem__(self, key):
        if key in self.columns:
            return self.database.get(f"SELECT {key} FROM {self.table_name}")
        else:
            raise KeyError(f"Column {key} not found in table {self.table_name}")

    def __setitem__(self, key, value):
        if key in self.columns:
            self.database.run(f"UPDATE {self.table_name} SET {key} = ?", value)
        else:
            raise KeyError(f"Column {key} not found in table {self.table_name}")

    def __delitem__(self, key):
        if key in self.columns:
            self.database.run(f"ALTER TABLE {self.table_name} DROP COLUMN {key}")
            self.columns.remove(key)
        else:
            raise KeyError(f"Column {key} not found in table {self.table_name}")

    def __iter__(self):
        for column in self.columns:
            yield column

    def __len__(self):
        return len(self.columns)

    def __contains__(self, key):
        return key in self.columns

    def __repr__(self):
        return f"DynamicTable({self.table_name}, {self.database})"

    def __str__(self):
        return f"DynamicTable({self.table_name}, {self.database})"