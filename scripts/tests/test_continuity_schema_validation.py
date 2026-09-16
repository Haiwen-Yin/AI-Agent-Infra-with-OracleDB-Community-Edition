"""Migration validation must distinguish semantic CHECK drift from formatting."""
import pytest
from lib.continuity_schema_validation import check_expression,default_expression


def test_native_string_defaults_preserve_literal_identity():
    assert default_expression("'TASK'::character varying")=="'TASK'"
    assert default_expression(" ('TASK') ")=="'TASK'"
    assert default_expression("'Task'")!="'TASK'"
    assert default_expression("'a (b)'::text")=="'a (b)'"
    assert default_expression(' CURRENT_TIMESTAMP ')== 'CURRENT_TIMESTAMP'


def test_vendor_array_and_casts_preserve_check_semantics():
    expected="STATUS IN ('ACTIVE','RETIRED')"
    pg="((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'RETIRED'::character varying])::text[]))"
    assert check_expression(expected)==check_expression(pg)
    assert check_expression(expected)==check_expression('"STATUS" IN (\'RETIRED\',\'ACTIVE\')')


def test_changed_boolean_grouping_and_states_are_not_equivalent():
    assert check_expression("(A=1 OR B=2) AND C=3")!=check_expression("A=1 OR (B=2 AND C=3)")
    assert check_expression("STATUS IN ('ACTIVE','RETIRED')")!=check_expression("STATUS IN ('ACTIVE','DELETED')")
    assert check_expression('VERSION>0')!=check_expression('VERSION>=0')
    assert check_expression('X IS NULL')!=check_expression('X IS NOT NULL')


@pytest.mark.parametrize('value',['UNTRUSTED_FUNCTION(X)','VERSION+1>0','VERSION>0; DROP TABLE X','(X=1','X=1)'])
def test_unsupported_or_malformed_checks_fail_closed(value):
    with pytest.raises((ValueError,IndexError)):
        check_expression(value)
