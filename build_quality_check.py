import argparse
import json
import logging
import requests
import sys
import textwrap
import time


class CheckBuildException(Exception):
    pass

class CheckBuidlHelpFormatter(argparse.HelpFormatter):
    def _fill_text(self, text, width, indent):
        return "\n".join([textwrap.fill(line, width) for line in textwrap.indent(textwrap.dedent(text), indent).splitlines()])


class CheckBuildStatus:


    VERSIONS_URL = 'https://api.rollbar.com/api/1/versions/{}'

    SUCCESS = 0
    NEW_ITEMS = 1
    REACTIVATED_ITEMS = 2
    NEW_AND_REACTIVATED_ITEMS = NEW_ITEMS + REACTIVATED_ITEMS
    GENERAL_ERROR = 100
    CHECK_BUILD_ERROR = 101

    REQUEST_RETRIES = 3

    def __init__(self, access_token, code_version, environment,
                 item_threshold, num_checks, check_seconds):
        """
        access_token - Rollbar project access token with read scope
        code_version - Typically a GIT commit SHA
        environment - The environment the code is running in
        item_threshold - If item count <= item_threshold, the build is a SUCCESS
        num_checks - Number of times Rollbar is checked for item counts
                     This can be used in progressive deployments
        check_seconds - Number of seconds between checking Rollbar
        """

        # verify that parameters are within allowed ranges
        CheckBuildStatus.validate_input(access_token, code_version, environment,
                                        item_threshold, num_checks, check_seconds)

        self.access_token = access_token
        self.code_version = code_version
        self.environment = environment

        self.item_threshold = item_threshold
        self.num_checks = num_checks
        self.check_seconds = check_seconds

        # dictionary with totals of the new, reactivater, etc. Rollbar items
        self.item_totals = None

        self.log_init_info()

    @staticmethod
    def validate_input(access_token: str, code_version: str, environment: str,
                       item_threshold: int, num_checks: int, check_seconds: int):

        """
        verify that each parameter has an allowed value
        """

        # access_token is 36 character alpha_numeric
        is_str = isinstance(access_token, str)
        is_alpha_num = access_token.isalnum()
        str_len = len(access_token)

        if is_str == False or is_alpha_num == False or str_len != 32:
            raise ValueError('The access_token argument is not valid')

        # code_version alpha_numeric (less than 200 chars)
        is_str = isinstance(code_version, str)
        str_len = len(code_version)

        if is_str == False or str_len > 200:
            raise ValueError('The code_version argument is not valid')

        # environment alpha_numeric with: ., _, or - (less than 200 chars)
        environment = environment.replace('.', '')
        environment = environment.replace('-', '')
        environment = environment.replace('_', '')
        is_str = isinstance(environment, str)
        is_alpha_num = environment.isalnum()
        str_len = len(environment)

        if is_str == False or is_alpha_num == False or str_len > 200:
            raise ValueError('The environment argument is not valid')

        is_int = isinstance(item_threshold, int)
        if is_int == False or item_threshold < 0:
            raise ValueError('The item_threshold argument is not valid')

        is_int = isinstance(num_checks, int)
        if is_int == False or num_checks < 1:
            raise ValueError('The num_checks argument is not valid')

        is_int = isinstance(check_seconds, int)
        if is_int == False or check_seconds < 1:
            raise ValueError('The check_seconds argument is not valid')



    def determine_build_quality(self):
        """
        determine the quality of this code_version/environment

        returns:
            0 - Success - No items;
            1 - New items;
            2 - Reactivated items;
            3 - New and Reactivated items;
            100 - General Error;
            101 - Invalid response code from call to Rollbar Versions API;
            
        """

        status = self.GENERAL_ERROR
        try:
            
            # if success sleep for a bit ancd check again later 
            # (can be used in progressive deployments)
            for i in range(0, self.num_checks):
                self.log_check_info(i+1)
                status = self.get_version_status()

                if status == self.SUCCESS:
                    time.sleep(self.check_seconds)
                else:
                    break
    
        except CheckBuildException as cb_ex:
            logging.error('CheckBuildException', exc_info=cb_ex)
            status = self.CHECK_BUILD_ERROR
        except Exception as ex:
            logging.error('General Error', exc_info=ex)

        return status


    def get_version_status(self):
        """
        Call the Rollbar Versions API, check the returned JSON
        Return the status of the application 
        """

        web_resp_text = self.get_version_json_data()

        self.calculate_item_totals(web_resp_text)
        self.log_item_totals_info()
        
        status = self.calculate_status()
        self.log_status(status)

        return status
    

    def get_version_json_data(self):
        """
        Make call to Rollbar Versions API
        Return the response JSON string 
        """

        # retry a few times if request fails
        resp : requests.Response
        for i in range(0, self.REQUEST_RETRIES):
            resp = self.make_versions_api_call()

            if not resp or resp.status_code != 200:
                time.sleep(3)
            else:
                break

        if resp is None:
            raise CheckBuildException('Invalid web response resp = None')
        elif resp.status_code != 200:
            msg = 'Invalid web response status code: {}'.format(resp.status_code)
            raise CheckBuildException(msg)

        return resp.text


    def make_versions_api_call(self):
        """
        Call Rollbar Versions API. 
        Return Response object
        """

        resp = None
        try:
            url = self.VERSIONS_URL.format(self.code_version)
            params = {'environment': self.environment}
            headers = {'X-Rollbar-Access-Token': self.access_token}

            resp = requests.get(url, params=params, headers=headers)
        except Exception as ex:
            logging.error('Error making request to Rollbar Versions API', exc_info=ex)


        print(url)
        print(resp.text)
        print(resp.status_code)

        return resp

    
    def calculate_item_totals(self, web_resp_text):
        """
        Get the counts for each type of item new, reactivated, repeated, resolved
        """

        json_data = json.loads(web_resp_text)
        # see https://explorer.docs.rollbar.com/#tag/Versions 
        item_stats = json_data['result']['item_stats']

        item_totals = {}
        item_totals['new'] = CheckBuildStatus.get_error_and_higher_count(item_stats['new'])
        item_totals['reactivated'] = CheckBuildStatus.get_error_and_higher_count(item_stats['reactivated'])
        item_totals['repeated'] = CheckBuildStatus.get_error_and_higher_count(item_stats['repeated'])
        item_totals['resolved'] = CheckBuildStatus.get_error_and_higher_count(item_stats['resolved'])

        self.item_totals = item_totals


    def calculate_status(self):
        """
        determine the status of this code_version/environment
        """

        status = self.SUCCESS

        total = self.item_totals['new'] + self.item_totals['reactivated']

        if total > self.item_threshold and self.item_totals['new'] > 0:
            status += self.NEW_ITEMS
        if total > self.item_threshold and self.item_totals['reactivated'] > 0:
            status += self.REACTIVATED_ITEMS

        return status

    def log_init_info(self):

        logging.info('###')
        logging.info('###########################################################')
        logging.info('###')
        logging.info('### CHECKING BUILD QUALITY WITH ROLLBAR')
        logging.info('###')
        logging.info('### code_version = %s', self.code_version)
        logging.info('### environment = %s', self.environment)
        logging.info('###')
        logging.info('### item_threshold = %s', self.item_threshold)
        logging.info('###')
        logging.info('### num_checks = %s', self.num_checks)
        logging.info('### check_seconds = %s', self.check_seconds)
        logging.info('###')
        logging.info('###########################################################')

    def log_check_info(self, current_check):

        logging.info('###')
        logging.info('### check %s of %s checks', current_check, self.num_checks)
        logging.info('###')

    
    def log_item_totals_info(self):

        logging.info('###')
        logging.info('### Item counts (Error and Critical level)')
        logging.info('###')
        logging.info('### new items = %s', self.item_totals['new'])
        logging.info('### reactivated items = %s', self.item_totals['reactivated'])
        logging.info('### repeated items = %s', self.item_totals['repeated'])
        logging.info('### resolved items = %s', self.item_totals['resolved'])
        logging.info('###')
        logging.info('###########################################################')


    def log_status(self, status):

        msg = 'FAILURE'
        if status == 0:
            msg = 'SUCCESS'

        logging.info('###')
        logging.info('### status = %s (status_code = %s)', msg, status)
        logging.info('###')
        logging.info('###########################################################')
        logging.info('###')

      
    @staticmethod
    def get_error_and_higher_count(item_stats: dict):
        """
        Get the count of items of level Error and Critical in item_stats dict
        """

        error = item_stats['error']
        critical = item_stats['critical']
        total = error + critical

        return total


def parse_args():

    desc =  f'''
        Check build quality with Rollbar

        Returns:

        0 - Success - No new items
        1 - New Items - New items of level Error or Critical
        2 - Reactivated Items - Reactivated items of level Error or Critical
        3 - New and Reactivated Items - New and Reactivated items of level Error or Critical
        100 - General Error
        101 - Web Request Error
        '''

    parser = argparse.ArgumentParser(description=desc, 
                                     formatter_class=CheckBuidlHelpFormatter)

    # required
    parser.add_argument('--access-token', type=str, required=True, 
        help='Rollbar project access token with read scope')
    parser.add_argument('--code-version', type=str, required=True, 
                        help='The code version of the application')
    parser.add_argument('--environment', type=str, required=True,
        help='The environment the application is running in')

    # optional
    parser.add_argument('--item-threshold', type=int, default=0, 
        help='The number of items above which quality is considered Failed')
    
    # optional
    parser.add_argument('--checks', type=int, default=1, 
        help='The number of times you check the item counts. Used for progressive deployments')
    parser.add_argument('--check-seconds', type=int, default=1, 
        help='The number of seconds between each item count check')


    args = parser.parse_args()
    
    return args 


if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO,
                        format='%(process)d-%(levelname)s-%(message)s',
                        handlers=[logging.StreamHandler()]
                        )
   
    args = parse_args()
    check = CheckBuildStatus(args.access_token, args.code_version, args.environment,
                             args.item_threshold, args.checks, args.check_seconds)

    status = check.determine_build_quality()

    sys.exit(status)
