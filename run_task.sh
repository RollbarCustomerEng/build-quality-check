#
# Requires Environment Variable ROLLBAR_READ_TOKEN 
# export ROLLBAR_READ_TOKEN=*******
#
# TWO ARGUMENTS
# args: $1=code_version $2=environment
#

echo "###"
echo "###"
echo "### CHECKING ROLLBAR FOR NEW AND REACTIVATED ERRORS"
echo "###"
echo "###"

python3 build_quality_check.py --access-token $ROLLBAR_READ_TOKEN --code-version $1 --environment $2
ret_code=$?
echo "Exit code $ret_code"
exit $ret_code
