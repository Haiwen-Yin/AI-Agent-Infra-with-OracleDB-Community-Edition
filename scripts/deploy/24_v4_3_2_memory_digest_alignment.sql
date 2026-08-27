-- v4.3.2 digest alignment for Memory adopted before the SHA-256 policy.
-- This is intentionally a separate journaled step: changing step 23 would
-- invalidate the checksum recorded by an already upgraded installation.
UPDATE CX_MEMORY_VERSIONS
   SET CONTENT_DIGEST = RAWTOHEX(STANDARD_HASH(
       DBMS_LOB.SUBSTR(NVL(BODY_TEXT, TO_CLOB('')), 32767, 1), 'SHA256'
   ))
 WHERE LEGACY_ENTITY_ID IS NOT NULL
   AND VERSION_NUMBER = 1;
