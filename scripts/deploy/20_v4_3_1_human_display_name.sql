-- v4.3.1 Human display-name extension.
-- Authentication usernames and immutable Principal IDs remain separate.

DECLARE
    PROCEDURE add_column(p_table VARCHAR2, p_column VARCHAR2, p_definition VARCHAR2) IS
        l_count NUMBER;
    BEGIN
        SELECT COUNT(*) INTO l_count FROM USER_TAB_COLUMNS
         WHERE TABLE_NAME = UPPER(p_table) AND COLUMN_NAME = UPPER(p_column);
        IF l_count = 0 THEN
            EXECUTE IMMEDIATE 'ALTER TABLE ' || p_table || ' ADD (' || p_column || ' ' || p_definition || ')';
        END IF;
    END;
BEGIN
    add_column('CX_PRINCIPALS', 'DISPLAY_NAME', 'VARCHAR2(256)');
    add_column('CX_REGISTRATION_REQUESTS', 'DISPLAY_NAME', 'VARCHAR2(256)');
END;
/
