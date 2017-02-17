#!/usr/bin/env python
# Copyright 2017 VMware, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# -------------------------------------------------------------------------------------------
# Updates ESX with vSphere Docker Volume Service 0.11 (and earlier)
#  to 0.11.1 and further
#
# This code expects to be places in  /usr/lib/vmware/vmdkops/bin/ to pick up correct modules.
# -------------------------------------------------------------------------------------------

#import os
import os.path
import sqlite3
import sys
import shutil

import vmdk_ops
# vmdkops python utils are in PY_LOC, so add to path.
sys.path.insert(0, vmdk_ops.PY_LOC)

import vmdk_utils
import auth
import auth_data_const
import auth_data
from error_code import ErrorCode, error_code_to_message

# Hard coded UUD for default tenant.
# TBD - sPick up from Lipings code when it's in
STATIC_UUID = '_12345'

# CLI return codes
OK = 0
ERROR = 1

def main():
    """
    This code updates ESX with vSphere Docker Volume Service 0.11 (and earlier)
    to 0.11.1 and further, by moving _DEFAULT tenant ID to well known and static UUID,
    and then correcting directories layout and auth_db tables to comply with new UUID.

    Specifically, it does the following:
    - Checks if AUTH_DB exists.
      If it does not, exit with a message - it means nothing to patch on this ESX
    - Gets uuid (aka "old_uuid') for _DEFAULT tenant from DB.
      If it already STATIC_UUID , exit with a message - nothing to patch
    - Stops the service
    - backs up the DB
    - scans through all <datastore>/volumes/dockvols and
        - mkdir STATIC_UUID, if it does not exist
        - move all from old_uuid to STATIC_UUID
        - symlinks "_DEFAULT" to STATIC_UUID
    In single DB transcation
        - replaces old_uuid with STATIC UUID in tenant_id field for all tables:
          (privileges, vms,  tenants, volumes)
    starts the service , and if all good removes backup DB

    NOTE: this does not delete any data, so the Docker volumes will stay around
          no matter if the code succeeds or fails
    """

    stop_service = False  # makes debugging faster. TBD - test and set to true

    dbfile = auth_data.AUTH_DB_PATH

    # STEP: check DB presense and fetch old_uuid
    if not os.path.isfile(dbfile):
        print("Config DB", dbfile, "is not found, nothing to update - existing.")
        sys.exit(0)

    auth_mgr = auth_data.AuthorizationDataManager(dbfile)
    auth_mgr.connect()
    error_msg, tenant = auth_mgr.get_tenant(auth.DEFAULT_TENANT)
    if error_msg:
        print(error_code_to_message[ErrorCode.TENANT_NOT_EXIST].format(auth.DEFAULT_TENANT), "- exiting")
        sys.exit(ERROR)

    old_uuid = tenant.id
    if old_uuid == STATIC_UUID:
        print("All seems good in DB, _DEFAULT uuid is already", old_uuid, " - exiting")
        sys.exit(OK)


    # STEP: Stop the service and back up the DB
    backup = dbfile + ".bck"
    print("Backing up Config DB to ", backup)
    shutil.copy(dbfile, backup)

    print("Stopping vmdk-opsd  service")
    if stop_service:
        os.system("/etc/init.d/vmdk-opsd stop")

    # STEP : convert dir names to new UUID if needed.
    print("Starting conversion of _DEFAULT tenant directry names. old_uid is ", old_uuid, " ...")
    stores = vmdk_utils.get_datastores()
    if not stores:
        print("Docker volume storage is not initialized - skipping directories patching")
    else:
        for ds in stores:
            name, uuid, path = ds
            print("  Working on Datastore ", name)
    print("Done")

    # STEP: patch database
    print("working on DB patch...")
    cursor = auth_mgr.conn.cursor() #  it is supposed to be connected by now
    # TBD DEBUG - conever to execute/execute many and debug

    # sql for update the DB
    # note that:
    #       {0} is old_uuid
    #       {1} is new_uuid
    #       {2} is tmp name
    #       {3} is description
    #       {4} is default DB for _DEFAULT tenant
    #       {5} is the name ("_DEFAULT") for default tenant
    # TBD - use named params
    sql_query_template = \
    """
    BEGIN TRANSACTION;
        -- insert temp record to make foreign key happy
        INSERT INTO tenants VALUES ( '{1}', '{2}', '{3}', '{4}' ) ;

        -- update the tables
        UPDATE vms SET tenant_id = '{1}' WHERE tenant_id = '{0}';
        UPDATE volumes SET tenant_id = '{1}' WHERE tenant_id = '{0}';
        UPDATE privileges SET tenant_id = '{1}' WHERE tenant_id = '{0}';

        -- recover _DEFAULT tenant record
        DELETE FROM tenants WHERE id = '{0}';
        UPDATE tenants set name = '_DEFAULT' where id = '{1}';
    COMMIT TRANSACTION;
    """

    tmp_tenant_name = "__tmp_name_upgrade_0_11"
    sql_query = sql_query_template.format(old_uuid, STATIC_UUID, tmp_tenant_name,
                                          tenant.description, tenant.default_datastore_url,
                                          auth.DEFAULT_TENANT)
    print("Query to execute (skipping for now)")
    # print(sql_query)
    # TBD !!! cursor.executescript(sql_query)

    cursor.execute("SELECT * from tenants")
    for r in cursor.fetchone():
        print(r)
    print("Done")

    # STEP: restart the service
    print("Starting vmdk-opsd  service")
    if stop_service:
        os.system("/etc/init.d/vmdk-opsd start")

    # TBD: remove backup ?
    print ("*** ALL DONE ***")


if __name__ == "__main__":
    main()

