import sys
import os

from ctbb_pipeline_library import ctbb_pipeline_library as ctbb_lib
import pypeline as pype
from pypeline import mutex,load_config

from os.path import abspath

def usage():
    print('usage: ctbb_pipeline_diff.py /path/to/config/file.yaml /path/to/library')
    print('    Copyright (c) John Hoffman 2016')
    
if __name__=="__main__":

    if len(sys.argv)<3:
        usage()
        sys.exit()

    else:

        # Get our command line arguments (library and config file)
        config_filepath=sys.argv[1]  ## Filepaths in configuration will target the original run path. This WILL NOT WORK if the directory has been moved.
        library_filepath=sys.argv[2] ## Relocated library path (could be original, but will also self-correct if the library has been moved)

        library=ctbb_lib(library_filepath)
        
        # Generate the list of cases that we wanted
        recon_list_desired=[]
        
        config=load_config(config_filepath)

        print("Looking for recons in: {}".format(abspath(library_filepath)))
        print("Using configuration file: {}".format(abspath(config_filepath)))
        print("Config file points to: {}".format(os.path.dirname(config["case_list"])))
        print("")
        
        ########
        library_root=os.path.dirname(os.path.dirname(library_filepath))
        case_list_root=os.path.dirname(config['case_list'])

        if library_root!=case_list_root:
            print("WARNING: Library and case list root directories are different.")
            print("This is likely due to the library being relocated after processing")
            print("Attempting to use library root to find required files... (this may not work!)")
            print("")
            
            print("Old case list path: {}".format(config["case_list"]))                        
            config["case_list"]=os.path.join(library_root,os.path.basename(config["case_list"]))
            print("New case list path: {}".format(abspath(config["case_list"])))
            print("")

            relocated_flag=True
        else:
            relocated_flag=False

        ########

        case_list=pype.case_list(config['case_list']) # Filepaths of raw data
        
        case_list_hashes=library.__get_case_list__() # 2 way hash dict case list

        for c in case_list.case_list:
            case_hash=case_list_hashes[c]

            if not c:
                continue
            for dose in config['doses']:
                for st in config['slice_thicknesses']:
                    for kernel in config['kernels']:

                        # build the individual dictionary items
                        d={
                            'org_raw_filepath':str(c),
                            'slice_thickness':str(st),
                            'pipeline_id':str(case_hash),
                            'dose':str(dose),
                            'kernel':str(kernel),
                            'img_series_filepath':os.path.join(library.path,
                                                               'recon',
                                                               str(dose),
                                                               '{}_k{}_st{}'.format(case_hash,kernel,st),
                                                               'img',
                                                               '{}_d{}_k{}_st{}.img'.format(case_hash,dose,kernel,st))
                            }


                        if relocated_flag:
                            org_raw_base=d["org_raw_filepath"].split("raw/")[1]
                            d["org_raw_filepath"]=os.path.join(abspath(library_root),'raw',org_raw_base)

                        recon_list_desired.append(d)

        #Iterate through our list of desired reconstructions and check if we have it
        missing_cases=[];
        for d in recon_list_desired:
            if os.path.exists(d['img_series_filepath']):
                continue
            else:
                missing_cases.append(d)

        # Check if user wanted to add the missing cases back to the queue
        if not missing_cases:
            print("No missing cases found! Library is complete.")
        else:
            queue_strings=[];
            queue_file=os.path.join(library.path,'.proc','queue')
            for m in missing_cases:
                queue_strings.append(('%s,%s,%s,%s\n') % (m['org_raw_filepath'],m['dose'],m['kernel'],m['slice_thickness']));

            print("The following reconstructions are missing from the library:")
            for q in queue_strings:
                print(q.rstrip())

            print("")
            print("Adding reconstructions back to the queue...")
            with open(queue_file,'a') as f:
                for q_string in queue_strings:
                    f.write(q_string)

            print("")
            print("Library queue is now:")
            os.system("cat {}".format(queue_file))
            print("")

        print('done')
        
