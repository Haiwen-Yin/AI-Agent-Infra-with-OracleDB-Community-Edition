-- Oracle already uses the adapter-neutral v4.4.6 physical names.
UPDATE CX_IDENTITY_PLATFORM_POLICIES SET POLICY_VALUE = POLICY_VALUE
WHERE POLICY_KEY = 'portal_connection_platform_max';
COMMIT;
