#!/usr/bin/python

# check_repodata.py - a script for checking repo sync
# states of content synchronized with Spacewalk,
# Red Hat Satellite or SUSE Manager.
#
# 2014 By Christian Stankowic
# <info at stankowic hyphen development dot net>
# https://github.com/stdevel
#

from optparse import OptionParser
import xmlrpclib
import os
import stat
import getpass
import time
import glob
import datetime

#list of supported API levels
supportedAPI = ["11.1","12","13","13.0","14","14.0","15","15.0"]

if __name__ == "__main__":
        #define description, version and load parser
        desc='''%prog is used to check repo sync states of content synchronized with Spacewalk, Red Hat Satellite and SUSE Manager. Login credentials are assigned using the following shell variables:

                SATELLITE_LOGIN  username
                SATELLITE_PASSWORD  password

                It is also possible to create an authfile (permissions 0600) for usage with this script. The first line needs to contain the username, the second line should consist of the appropriate password.
If you're not defining variables or an authfile you will be prompted to enter your login information.

                Checkout the GitHub page for updates: https://github.com/stdevel/check_repodata'''
        parser = OptionParser(description=desc,version="%prog version 0.1")

        #-a / --authfile
        parser.add_option("-a", "--authfile", dest="authfile", metavar="FILE", default="", help="defines an auth file to use instead of shell variables")

        #-s / --server
        parser.add_option("-s", "--server", dest="server", metavar="SERVER", default="localhost", help="defines the server to use")

        #-d / --debug
        parser.add_option("-d", "--debug", dest="debug", default=False, action="store_true", help="enable debugging outputs")

        #-r / --repodata-only
        parser.add_option("-r", "--repodata-only", dest="repodataOnly", default=False, action="store_true", help="only checks repodata on file system, skipping Yum sync state inside Spacewalk")

        #-l / --channels
        parser.add_option("-l", "--channels", dest="channels", action="append", metavar="CHANNELS", help="defines one or more channels that should be checked")
	
	#-w / --warning-threshold
	parser.add_option("-w", "--warning-threshold", dest="warningThres", metavar="THRESHOLD", type="int", default=24, help="warning threshold in hours (default: 24)")
	
	#-c / --critical-threshold
	parser.add_option("-c", "--critical-threshold", dest="criticalThres", metavar="THRESHOLD", type="int", default=48, help="critical threshold in hours (default: 48)")

        #parse arguments
        (options, args) = parser.parse_args()

        #define URL and login information
        SATELLITE_URL = "http://"+options.server+"/rpc/api"

        #debug
        if options.debug: print "OPTIONS: {0}".format(options)
        if options.debug: print "ARGUMENTS: {0}".format(args)

        #check whether at least one channel was specified
        try:
                if len(options.channels) == 0:
                        #no channel specified
                        print "UNKNOWN: no channel(s) specified"
                        exit(3)
                else:
                        #try to explode string
                        if len(options.channels) == 1: options.channels = str(options.channels).strip("[]'").split(",")
                        if options.debug: print "DEBUG: ",options.channels
        except:
                #size excpetion, no channel specified
                print "UNKNOWN: no channel(s) specified"
                exit(3)

        #setup client and key depending on mode if needed
	if not options.repodataOnly:
        	client = xmlrpclib.Server(SATELLITE_URL, verbose=options.debug)
	        if options.authfile:
        	        #use authfile
	                if options.debug: print "DEBUG: using authfile"
        	        try:
                	        #check filemode and read file
                        	filemode = oct(stat.S_IMODE(os.lstat(options.authfile).st_mode))
	                        if filemode == "0600":
        	                        if options.debug: print "DEBUG: file permission ("+filemode+") matches 0600"
                	                fo = open(options.authfile, "r")
                        	        s_username=fo.readline()
                                	s_password=fo.readline()
	                                key = client.auth.login(s_username, s_password)
        	                else:
                	                if options.verbose: print "ERROR: file permission ("+filemode+") not matching 0600!"
                        	        exit(1)
	                except OSError:
        	                print "ERROR: file non-existent or permissions not 0600!"
                	        exit(1)
	        elif "SATELLITE_LOGIN" in os.environ and "SATELLITE_PASSWORD" in os.environ:
        	        #shell variables
                	if options.debug: print "DEBUG: checking shell variables"
	                key = client.auth.login(os.environ["SATELLITE_LOGIN"], os.environ["SATELLITE_PASSWORD"])
	        else:
	                #prompt user
	                if options.debug: print "DEBUG: prompting for login credentials"
	                s_username = raw_input("Username: ")
	                s_password = getpass.getpass("Password: ")
	                key = client.auth.login(s_username, s_password)
	
	        #check whether the API version matches the minimum required
	        api_level = client.api.getVersion()
	        if not api_level in supportedAPI:
	                print "ERROR: your API version ("+api_level+") does not support the required calls. You'll need API version 1.8 (11.1) or higher!"
        	        exit(1)
	        else:
        	        if options.debug: print "INFO: supported API version ("+api_level+") found."
	
	#check repo sync state
	errors = []
	critError = False
	if not options.repodataOnly:
		for channel in options.channels:
			#get channel details
			details = client.channel.software.getDetails(key, channel)
			if "yumrepo_last_sync" in details:
				#check last sync state if given (not all channels provide these information - e.g. RHEL channels)
				stamp = datetime.datetime.strptime(str(details["yumrepo_last_sync"]), "%Y%m%dT%H:%M:%S")
				now = datetime.datetime.today()
	                	diff = now - stamp
	                	diff = time.strftime("%H",time.gmtime(diff.seconds))
		                if options.debug: print "DEBUG: Yum sync difference for channel '"+channel+"' is "+diff+" hours"
		                if int(diff) >= options.criticalThres:
					if options.debug: print "DEBUG: Yum sync difference (" + str(diff) + ") is higher than critical threshold (" + str(options.criticalThres) + ")"
                		        if channel not in errors: errors.append(channel)
			                critError = True
		                elif int(diff) >= options.warningThres:
					if options.debug: print "DEBUG: Yum sync difference (" + str(diff) + ") is higher than warning threshold (" + str(options.warningThres) + ")"
		                        if channel not in errors: errors.append(channel)

	#check repodata age
	for channel in options.channels:
		#check for *.new files (indicator for running repodata rebuild)
		newfiles = glob.glob("/var/cache/rhn/repodata/"+channel+"/*.new")
		if len(newfiles) >= 1:
			#rebuild in progress, check timestamp of first file
			errors.append(channel)
		#check for outdated repodata
		stamp = datetime.datetime.fromtimestamp(os.path.getmtime("/var/cache/rhn/repodata/"+channel+"/repomd.xml"))
		now = datetime.datetime.today()
		diff = now - stamp
		diff = time.strftime("%H",time.gmtime(diff.seconds))
		if options.debug: print "DEBUG: Difference for /var/cache/rhn/repodata/"+channel+"/repomd.xml is "+diff+" hours"
		if int(diff) >= options.criticalThres:
			if options.debug: print "DEBUG: File system timestamp difference (" + str(diff) + ") is higher than critical threshold (" + str(options.criticalThres) + ")"
			if channel not in errors: errors.append(channel)
			critError = True
			if options.debug: print "DEBUG: File system timestamp difference (" + str(diff) + ") is higher than warning threshold (" + str(options.criticalThres) + ")"
		elif int(diff) >= options.warningThres:
			if channel not in errors: errors.append(channel)
	
	#exit with appropriate Nagios / Icinga plugin return code and message
	if options.debug: print "ERRORS: " + str(errors)
	if len(errors) >= 1:
		if critError == True:
			print "CRITICAL: At least one channel is still syncing or outdated:",str(errors).strip("[]")
			exit(2)
		else:
			print "WARNING: At least one channel is still syncing or outdated:",str(errors).strip("[]")
			exit(1)
	else:
		print "OK: Specified channels are synchronized:",str(options.channels).strip("[]")
		exit(0)
