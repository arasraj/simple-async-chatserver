import sys
import time
import socket
import select

class ChatServer:

  def __init__(self):
    self.serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.host = ''  
    self.port = int(sys.argv[1])
  
    self.serversocket.setblocking(0)
    self.serversocket.bind((self.host, self.port))
    self.serversocket.listen(5)

    self.epoll = select.epoll()
    self.epoll.register(self.serversocket.fileno(), select.EPOLLIN)
    
    self.active_users = {} 
    self.inputs = {}
    self.outputs = {}
    self.roomlist = {}
    self.userdataconns = {}
    
  def server_loop(self):
    while (1):
      events = self.epoll.poll(1)
      for fileno, event in events:
        if fileno == self.serversocket.fileno():
          try:
            while (1):
              conn, addr = self.serversocket.accept()
              conn.setblocking(0)
              self.epoll.register(conn.fileno(), select.EPOLLIN | select.EPOLLET | select.EPOLLHUP)
              self.add_user_conn(conn.fileno(), conn)
              self.inputs[conn.fileno()] = ''
              self.outputs[conn.fileno()] = []
          except socket.error: pass
        elif event & select.EPOLLIN:
          self.inputs[fileno] = '' #reset from previous request
          self.sock_error[fileno] = 0
          try:
            now = time.time()
            completed = True
            while (1):
              received_data = self.user_conn(fileno).recv(1024)
              
              then = time.time()
              if then > now + 0.4:
                self.logout_user(fileno)
                print 'infinite sock stream'
                completed = False
                break

              self.inputs[fileno] += received_data 
          except socket.error: pass
 
          if completed:
            print self.inputs[fileno]
            if self.inputs[fileno][-2:] != '\r\n':
              self.outputs[fileno].append('Error: no end of input\r\n')
              self.epoll.modify(fileno, select.EPOLLOUT | select.EPOLLET | select.EPOLLHUP)
              print 'no end of line'
              break
        
            action = self.inputs[fileno].split()
            sendtofd_list = self.process_action(action, fileno)

            if sendtofd_list:
              for fd in sendtofd_list:
                self.epoll.modify(fd, select.EPOLLOUT | select.EPOLLET | select.EPOLLHUP)

        elif event & select.EPOLLOUT:
          try:
            while (len(self.outputs[fileno][0]) > 0):
              sent = self.user_conn(fileno).send(self.outputs[fileno][0]) 
              self.outputs[fileno][0] = self.outputs[fileno][0][sent:]
          except socket.error: pass

          if len(self.outputs[fileno][0]) == 0:
            self.outputs[fileno].pop(0)
          self.epoll.modify(fileno, select.EPOLLIN | select.EPOLLET | select.EPOLLHUP)

        #does not work
        elif event & select.EPOLLHUP:
          self.epoll.unregister(fileno)
          self.user_conn(fileno).close()
          del self.userdataconns[fileno]
 
  def process_action(self, action, fileno):
    user_cmd = action[0].lower()

    if user_cmd == 'login' and len(action) == 2:          
      name = action[1].lower()
      if name not in self.active_users.keys():
        self.active_users[name] = fileno #for efficiency on msg sends
        self.add_user_name(fileno, name) #to avoid continuous lookups in realtime envrionment. sacrifice space for speed
        self.outputs[fileno].append('OK\r\n')
      else:
        self.outputs[fileno].append('Username already taken!\r\n')
      return [fileno]
    elif user_cmd == 'msg' and len(action) >= 3:
      if action[1].lower()[0] == '#':
        #if room exists
        return self.room_broadcast(fileno, action[1].lower(),  ' '.join(action[2:]))  
      elif action[1].lower() in self.active_users:
        self.outputs[self.active_users[action[1].lower()]].append('GOTUSERMSG ' + self.user_name(fileno) + ' ' + ' '.join(action[2:]) + '\r\n')     
        return [int(self.active_users[action[1].lower()])]
    elif user_cmd == 'join' and len(action) == 2:
      roomname = action[1].lower()
      if roomname not in self.roomlist:
        #if no room create it
        self.roomlist[roomname] = Room(roomname)
      #add person to room
      #if user already in room dont add
      username = self.user_name(fileno)
      if username not in self.roomlist[roomname].roomlist:
        self.roomlist[roomname].roomlist.append(username)
        self.outputs[fileno].append('OK\r\n')
      return [fileno]
    elif user_cmd == 'leave' and len(action) == 2:
      self.roomlist[action[1].lower()].leave((self.user_name(fileno)))
      self.outputs[fileno].append('OK\r\n')
      return [fileno]
    elif user_cmd == 'list' and len(action) == 2:
      user_list = self.roomlist[action[1].lower()].whos_here()
      self.outputs[fileno].append(user_list + '\r\n')
      return [fileno]
    #never get here due to epoll issues
    elif user_cmd == 'logout' and len(action) == 1:
      username = self.user_name(fileno) #put this call at top
      for room in self.roomlist:
        if username in room:
          room.leave(username)
      self.epoll.unregister(fileno)
      self.user_conn(fileno).close()
      del self.userdataconns[fileno]  #possible change
    else:
      self.outputs[fileno].append('ERROR\r\n')
      print 'ERROR'
      return [fileno] 
      
  def logout_user(self, fileno):
    username = self.user_name(fileno) 
    for room in self.roomlist:
      if username in room:
        room.leave(username)
    del self.active_users[username]
    self.epoll.unregister(fileno)
    self.user_conn(fileno).shutdown(socket.SHUT_RDWR)
    self.user_conn(fileno).close()
    del self.userdataconns[fileno]  #possible change
  
  #obsolete?
  def fd_to_username(self, fileno):
    for key in self.active_users.keys():
      if self.active_users[key] == fileno:
        return key

  def room_broadcast(self, origin, roomname, message):
    room = self.roomlist[roomname]
    source = self.user_name(origin)
    fd_roomlist = []
    for person in room.roomlist:
      self.outputs[self.active_users[person]].append('GOTROOMMMSG %s %s %s\r\n' % (source, room.name,  message))
      fd_roomlist.append(self.active_users[person])
    return fd_roomlist 

  def user_conn(self, fd):
    return self.userdataconns[fd][0]

  def user_name(self, fd):
    return self.userdataconns[fd][1]

  def add_user_conn(self, fd, socket):
    self.userdataconns[fd] = [] 
    self.userdataconns[fd].append(socket)
    print self.userdataconns

  def add_user_name(self, fd, name):
    self.userdataconns[fd].append(name)

class Room:

  def __init__(self, name):
    self.name = name
    self.roomlist = []

  def whos_here(self):
    return '\n'.join(self.roomlist)

  def join(self, person):
    self.roomlist.append(person)

  def leave(self, person):
    self.roomlist.remove(person)


if __name__ == '__main__':
  chatserver = ChatServer()
  chatserver.server_loop()
