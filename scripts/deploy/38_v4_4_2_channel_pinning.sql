-- v4.4.2 additive governed Channel pinning.
-- Pinning changes inbox priority only.  It never changes membership, data
-- authority, Channel classification, or the message-derived activity clock.
DECLARE
  l_exists NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_exists FROM USER_TAB_COLUMNS
   WHERE TABLE_NAME = 'CX_CHANNELS' AND COLUMN_NAME = 'PINNED';
  IF l_exists = 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE CX_CHANNELS ADD (PINNED CHAR(1) DEFAULT ''N'' NOT NULL)';
  END IF;
  BEGIN
    EXECUTE IMMEDIATE 'CREATE INDEX IDX_CX_CHANNEL_PIN_ACTIVITY ON CX_CHANNELS(PINNED, UPDATED_AT, CHANNEL_ID)';
  EXCEPTION WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
  END;
END;
/
