'''
Primitive shell script to build a standalone client.py file from the client.py file.

- copy the client.py file to the current directory
- find and replace USERNAME and PASSWORD with the username and password of the user you want to use
'''

cp ../client.py .
sed -i 's/USERNAME = "exampleusername"/USERNAME = "'$USERNAME'"/g' client.py
sed -i 's/PASSWORD = "S3cr3t!password"/PASSWORD = "'$PASSWORD'"/g' client.py
python3 encode_py_base64.py client.py client_build.py
rm client.py
mv client_build.py client.py
