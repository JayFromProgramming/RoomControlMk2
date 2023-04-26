class ColumnWrapper:

    def __init__(self, table, pragma):
        self.table = table
        self.position = pragma[0]  # type: int
        self.name = pragma[1]  # type: str
        self.type = pragma[2]  # type: str
        self.not_null = pragma[3]  # type: int
        self.primary_key = pragma[5]  # type: int

        if self.primary_key:
            self.table.primary_keys.append(self)

    def validate(self, value):
        if self.not_null and value is None:
            raise ValueError(f"Column {self.name} cannot be null")
        if isinstance(value, list):  # If the value is a range of values then validate each value in the range
            for item in value:
                self.validate(item)
            return
        # Validate the duck type of the column is correct (aka if it is a string of an integer its still an integer)
        if self.type.upper() == "INTEGER":
            try:
                int(value)
            except ValueError:
                raise ValueError(f"Column {self.name} must of duck type {self.type}")
        elif self.type.upper() == "REAL":
            try:
                float(value)
            except ValueError:
                raise ValueError(f"Column {self.name} must of duck type {self.type}")
        elif self.type.upper() == "TEXT":
            if not isinstance(value, str) and not isinstance(value, int) and not isinstance(value, float):
                raise ValueError(f"Column {self.name} must of duck type {self.type}")
        elif self.type.upper() == "BLOB":
            if not isinstance(value, bytes):
                raise ValueError(f"Column {self.name} must of exact type {self.type}")
        elif self.type.upper() == "BOOLEAN":
            if not isinstance(value, bool):
                raise ValueError(f"Column {self.name} must of exact type {self.type}")
        else:
            raise ValueError(f"Column {self.name} has an unknown type {self.type}")

    def __str__(self):
        return f"[{self.position}]-{self.name}-{self.type}-{'NOT NULL' if self.not_null else 'NULL'}-{'PRIMARY KEY' if self.primary_key else ''}"

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        if isinstance(other, ColumnWrapper):
            return self.name == other.name
        elif isinstance(other, str):
            return self.name == other
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.name)

    def __contains__(self, item):
        return item == self.name

    def safe_value(self, value):
        """
        Returns a value that is safe to be inserted into a SQL statement
        :param column: The column that the value is for
        :param value: The value to be inserted
        :return:
        """
        if value is None:
            return "NULL"
        elif self.type == "TEXT":
            return f"'{value}'"
        elif self.type == "INTEGER":
            return str(value)
        elif self.type == "BOOLEAN":
            return str(value)
        elif self.type == "REAL":
            return str(value)
        elif self.type == "BLOB":
            return str(value)
        else:
            raise TypeError(f"Unknown column type {self.type}")
