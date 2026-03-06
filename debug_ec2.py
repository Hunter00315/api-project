import paramiko

pkey = paramiko.RSAKey.from_private_key_file('cloud-key-pair.pem')
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('13.53.123.150', username='ec2-user', pkey=pkey, timeout=10)

commands = [
    ('git_pull', 'cd /home/ec2-user/api-project && git pull origin main 2>&1'),
    ('create_table', 'cd /home/ec2-user/api-project && python3 setup_dynamodb.py 2>&1'),
    ('verify_table',
     'cd /home/ec2-user/api-project && python3 -c \''
     'import boto3,os;'
     '[os.environ.update({l.split("=",1)[0].strip():l.split("=",1)[1].strip()}) for l in open(".env") if "=" in l and not l.strip().startswith("#")];'
     'c=boto3.client("dynamodb",region_name="eu-north-1");'
     'print(c.describe_table(TableName="HealthcareSlots")["Table"]["TableStatus"])'
     '\' 2>&1'),
    ('restart_service', 'sudo systemctl restart healthcare-api && sleep 3 && sudo systemctl --no-pager status healthcare-api'),
    ('curl_slots', 'curl -s http://localhost:5000/slots 2>&1'),
]

for label, cmd in commands:
    print(f'\n{"="*60}\n[{label}]\n{"="*60}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print(out or err or '(no output)')

ssh.close()
print('\nDone.')

