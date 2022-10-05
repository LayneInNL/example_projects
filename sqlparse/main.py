import sqlparse
parsed = sqlparse.parse('select * from foo')[0]