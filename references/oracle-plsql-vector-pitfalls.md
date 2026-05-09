# Oracle 26ai PL/SQL Vector 类型陷阱与解决方案

**Version**: v0.1.0  
**Date**: 2026-05-09  
**Source**: oracle-memory-by-yhw v0.6.0 开发过程中的实际踩坑记录

---

## 陷阱 1: CAST(... AS VECTOR) 在 PL/SQL 中不支持

**错误信息**: `ORA-22849: Type VECTOR is not supported for this function or operator`

**问题代码**:
```sql
UPDATE MEMORIES
SET EMBEDDING = CAST('[-0.015, 0.023, ...]' AS VECTOR(1024))
WHERE ID = 1;
```

**解决方案**: 使用 `TO_VECTOR()` 函数 + CLOB 变量
```sql
DECLARE
    l_vec CLOB;
BEGIN
    l_vec := '[-0.015, 0.023, ...]';
    UPDATE MEMORIES
    SET EMBEDDING = TO_VECTOR(l_vec)
    WHERE ID = 1;
END;
```

**适用场景**: 所有需要在 PL/SQL 中插入/更新 VECTOR 类型的场景

---

## 陷阱 2: PL/SQL 不支持三元运算符

**错误信息**: `PLS-00049: bad bind variable` 或 `ORA-00911: invalid character`

**问题代码**:
```sql
SET RESULT_COUNT = v_first ? 0 : 1
```

**解决方案**: 使用 `CASE WHEN` 表达式
```sql
SET RESULT_COUNT = CASE WHEN v_first THEN 0 ELSE 1 END
```

---

## 陷阱 3: CURRVAL 不能跨语句使用

**错误信息**: `ORA-02287: sequence number not allowed here`

**问题代码**:
```sql
INSERT INTO TABLE (ID) VALUES (SEQ.NEXTVAL);
UPDATE TABLE SET NAME = 'test' WHERE ID = SEQ.CURRVAL;  -- ❌ 失败！
```

**解决方案**: 将 NEXTVAL 保存到变量中再使用
```sql
DECLARE
    v_id NUMBER;
BEGIN
    SELECT SEQ.NEXTVAL INTO v_id FROM DUAL;
    INSERT INTO TABLE (ID) VALUES (v_id);
    UPDATE TABLE SET NAME = 'test' WHERE ID = v_id;  -- ✅ 成功
END;
```

---

## 陷阱 4: SQLcl 执行 SQL 文件的正确方式

SQLcl 路径: `/root/sqlcl/sqlcl/bin/sql` (双层目录!)

```bash
# 正确方式
echo "SQL" | /root/sqlcl/sqlcl/bin/sql user/pass@conn @/full/path/to/file.sql
```

**注意**: SQLcl 不能用 `-c` 参数执行 SQL，必须用 `echo "SQL" | sql` 格式

---

## 陷阱 5: VECTOR_DISTANCE 子查询引用

**正确方式**: 使用子查询引用 VECTOR 列，不能在 WHERE 中直接比较两个向量列
```sql
SELECT n.label,
       VECTOR_DISTANCE(n.embedding,
           (SELECT embedding FROM memories WHERE id = :query_id),
           COSINE) as similarity
FROM memories n
WHERE n.embedding IS NOT NULL
ORDER BY similarity ASC
FETCH FIRST 10 ROWS ONLY;
```

---

## 快速参考卡片

| 场景 | ❌ 错误 | ✅ 正确 |
|------|---------|---------|
| PL/SQL 插入向量 | `CAST(str AS VECTOR(1024))` | `TO_VECTOR(clob_var)` |
| 条件赋值 | `x ? a : b` | `CASE WHEN x THEN a ELSE b END` |
| 获取序列值 | `SEQ.CURRVAL` (跨语句) | 先 `SELECT SEQ.NEXTVAL INTO var` |
| SQLcl 执行文件 | `sql user/pass @file.sql` | `echo "SQL" \| sql user/pass @/full/path/file.sql` |

---

**Last Updated**: 2026-05-09
