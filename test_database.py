import sqlite3

# 连接数据库
conn = sqlite3.connect('stock_selection.db')
cursor = conn.cursor()

# 检查表是否存在
tables = ['stock_basic', 'concept_board', 'stock_concept_relation', 'industry_board', 'stock_industry_relation']

for table in tables:
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}';")
    result = cursor.fetchone()
    if result:
        print(f"表 {table} 存在")
        # 检查表中的数据量
        cursor.execute(f"SELECT COUNT(*) FROM {table};")
        count = cursor.fetchone()[0]
        print(f"  数据量: {count}")
    else:
        print(f"表 {table} 不存在")

# 查看行业数据
print("\n行业数据示例:")
cursor.execute("SELECT * FROM industry_board LIMIT 10;")
industries = cursor.fetchall()
for industry in industries:
    print(f"  ID: {industry[0]}, 名称: {industry[1]}, 代码: {industry[2]}")

# 关闭连接
conn.close()
