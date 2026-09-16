-- Resolve the owner at deployment, independent of trigger CURRENT_USER semantics.
DECLARE owner_name VARCHAR2(128);
BEGIN
  SELECT USER INTO owner_name FROM DUAL;
  EXECUTE IMMEDIATE 'CREATE OR REPLACE TRIGGER CX415_TOOL_MCP_GUARD
BEFORE INSERT OR UPDATE OR DELETE ON TOOL_REGISTRY FOR EACH ROW
BEGIN
  IF SYS_CONTEXT(''USERENV'',''SESSION_USER'')<>''' || REPLACE(owner_name,'''','''''') || ''' THEN
    IF (INSERTING OR UPDATING) AND :NEW.MCP_EXPOSED=''Y'' THEN
      RAISE_APPLICATION_ERROR(-20090,''MCP exposure requires control-plane authority'');
    END IF;
    IF (UPDATING OR DELETING) AND :OLD.MCP_EXPOSED=''Y'' THEN
      RAISE_APPLICATION_ERROR(-20090,''An exposed tool requires control-plane authority'');
    END IF;
  END IF;
END;';
END;
/
