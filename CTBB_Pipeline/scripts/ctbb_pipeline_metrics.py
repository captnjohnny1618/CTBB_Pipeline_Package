# A script to mine queue item logs for data 

import sys
import os

import csv
import numpy as np
from datetime import datetime

from ctbb_pipeline_library import ctbb_pipeline_library 

def mine_qi_logfile(filepath):

    # Mine for the following key phrases:
    #     START/END: QUEUE ITEM
    #     START/END: FETCH RAW
    #     START/END: DOSE REDUCTION
    #     START/END: RECON

    metrics={}

    metrics['filename']=filepath
    print(filepath)
    
    # Grab the logfile
    with open(filepath,'r') as f:
        logfile=f.read().splitlines()

    def extract_logfile_time(keyphrase):
        t=datetime(1900,12,12)
        for line in logfile:
            if keyphrase in line:
                s=line.split(',')
                t=datetime.strptime(s[0],"%Y-%m-%d %H:%M:%S")

        return t

    metrics['start_time']=extract_logfile_time('START: QUEUE ITEM')
    metrics['end_time']=extract_logfile_time('END: QUEUE ITEM')
    
    # Total execution time:
    tdelta=extract_logfile_time('END: QUEUE ITEM')-extract_logfile_time('START: QUEUE ITEM')
    #print('Total time: %.2f' % tdelta.total_seconds());
    metrics['time_total']=tdelta.total_seconds()

    # Fetch time:
    tdelta=extract_logfile_time('END: FETCH RAW')-extract_logfile_time('START: FETCH RAW')
    #print('Time to retrieve raw data: %.2f' % tdelta.total_seconds());
    metrics['time_fetch_raw']=tdelta.total_seconds()    

    # Simdose execution time:
    tdelta=extract_logfile_time('END: DOSE REDUCTION')-extract_logfile_time('START: DOSE REDUCTION')
    #print('Dose reduction time: %.2f' % tdelta.total_seconds()); 
    metrics['time_dose_reduction']=tdelta.total_seconds()       

    # Recon execution time:
    tdelta=extract_logfile_time('END: RECON')-extract_logfile_time('START: RECON')
    #print('Recon time: %.2f' % tdelta.total_seconds());
    metrics['time_recon']=tdelta.total_seconds()

    return metrics

if __name__=="__main__":

    # CL input should be the "log" directory of a pipeline library

    logdir=sys.argv[1]
    files=[f for f in os.listdir(logdir) if os.path.isfile(os.path.join(logdir,f))]
    files=[os.path.join(logdir,f) for f in files]

    start_time=datetime.now();
    end_time=datetime.min;

    header_written=False
    with open(os.path.join(logdir,'metrics.csv'),'wb') as f:
        for filename in files:
            if 'qi' in filename:
                metrics_dict=mine_qi_logfile(filename)
                w=csv.DictWriter(f,metrics_dict.keys())

                if not header_written:
                    header_written=True
                    w.writeheader()

                w.writerow(metrics_dict);

                if metrics_dict['start_time']<start_time:
                    start_time=metrics_dict['start_time']

                if metrics_dict['end_time']>end_time:
                    end_time=metrics_dict['end_time']
                
    ## Read CSV and calculate summary data
    data=np.genfromtxt(os.path.join(logdir,'metrics.csv'),dtype=float,delimiter=',',names=True)

    # Calculate totals
    total_time                = data['time_total'].sum()
    total_recon_time          = data['time_recon'].sum()
    total_dose_reduction_time = data['time_dose_reduction'].sum()
    total_data_fetch_time     = data['time_fetch_raw'].sum()
                                
    # Calculate averages        
    avg_time                  = data['time_total'].mean()
    avg_recon_time            = data['time_recon'].mean()
    avg_dose_reduction_time   = data['time_dose_reduction'].mean()
    avg_data_fetch_time       = data['time_fetch_raw'].mean()

    avg_nonzero_dose_reduction_time = data['time_dose_reduction'].sum()/((data['time_dose_reduction']!=0).sum())
    avg_nonzero_data_fetch_time     = data['time_fetch_raw'].sum()/((data['time_fetch_raw']!=0).sum())

    with open(os.path.join(logdir,'summary_metrics.yml'),'w') as f:
        def printout(tag,value):
            f.write("%s: %s\n" % (str(tag),str(value)))

        tdelta=end_time-start_time;
        printout("real_time",tdelta.total_seconds())
            
        printout("total_time",total_time)
        printout("total_recon_time",total_recon_time)
        printout("total_dose_reduction_time",total_dose_reduction_time)
        printout("total_data_fetch_time",total_data_fetch_time)
        
        printout("avg_time",avg_time)
        printout("avg_recon_time",avg_recon_time)
        printout("avg_dose_reduction_time",avg_dose_reduction_time)
        printout("avg_data_fetch_time",avg_data_fetch_time)

        printout("avg_nonzero_dose_reduction_time",avg_nonzero_dose_reduction_time)
        printout("avg_nonzero_data_fetch_time",avg_nonzero_data_fetch_time)
