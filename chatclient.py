import sys
import socket
import select


def main():
  cs = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  host = sys.argv[1]
  port = int(sys.argv[2])

  cs.connect((host, port))

  running = 1

  while running:
    inputready, writeready, errready = select.select([0, cs], [], [])
    responses = ''
    for sock in inputready:
      if sock == cs:
        while (1):
          recv_data = cs.recv(1024)
          responses += recv_data
          if not recv_data or '\r\n' in recv_data:
            break
        print responses
      elif sock == 0:
        user_input = sys.stdin.readline().strip() 
        if user_input:
          if user_input == 'logout':
            cs.shutdown(socket.SHUT_RDWR)
            cs.close()
            print 'sent'
            running = 0
          else:
            cs.send(user_input + '\r\n')
 

if __name__ == '__main__':
  main()
