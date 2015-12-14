from .network.TcpClient import TcpClient
from .network.Msg import Msg, MsgType
from .network.TcpServer import P_TcpServer, T_TcpServer, TcpServer
from .network.Reports	import NetareaReport, MonitorReport

from time import sleep
from threading import Thread, RLock, Event
from multiprocessing import Process, Queue
from .Utility import serialize, unserialize
from copy import deepcopy
from math import ceil
from .Netarea import  MAX as NETAREA_MAX, NetRing
from enum import IntEnum
import logging
from collections import defaultdict

import traceback, sys

debug=True

FIRST_RATE			= 0.6 #proportion de netarea alloué la première fois

#Constantes used in Leader election
class Status(IntEnum):
	passive		= 0
	dummy		= 1	
	waiting		= 2
	candidate 	= 3
	leader		= 4
	
class Action(IntEnum): #msg.type
	ALG			= 0
	AVS			= 1
	AVSRP		= 2
	
class LogicalNode: # in a logical ring
	def __init__(self, host, port, monitors):
		"""
			monitors [ (host, port)]
		"""
		self.identity	= hash( (host, port) )
		self.host		= host
		self.port		= port
		self.status		= Status.candidate
		self.succ 		= self.get_succ(monitors) # <=>neighi
		self.cand_pred	= None #logical node
		self.cand_succ	= None #same
		
	def get_succ(self, monitors):
		tmp 			= monitors[ (self.host, self.port) ]
		tmp_monitors	= list(monitors.values())
		tmp_monitors.sort( 
			key=(lambda item : hash( (item.host, item.port) ) ) )
		
		i = tmp_monitors.index(tmp)
		
		if i != len(tmp_monitors)-1:
			return tmp_monitors[i+1]
		else :
			return tmp_monitors[0]		
		 
	def __ge__(self, node):#self>=
		return self.identity>=node.identity
	
	def __gt__(self, node):#self>
		return self.identity>node.identity
		
	def __le__(self, node):#self<=
		return self.identity<=node.identity
	
	def __lt__(self, node):#self<
		return self.identity<node.identity
		
	def __ne__(self, node):#self!=
		return self.identity!=node.identity
	
	def __eq__(self, node):
		return self.identity == node.identity
		
class MonServer(T_TcpServer):
	def __init__(self, port, monitors, ev_leader, masterReports, 
		slaveReports, netRing, Exit, monitors_lock, masters_lock, 
		slaves_lock, netRing_lock, Propagate):
			
		self.port			= port
		self.monitors		= monitors
		self.ev_leader		= ev_leader #to announce if it's the leader to Monitor
		
		T_TcpServer.__init__(self, Exit)
		
		self.client			= TcpClient()
		
		self.masterReports	= masterReports
		self.slaveReports	= slaveReports
		self.netRing		= netRing
		
		self.monitors_lock	= monitors_lock
		self.masters_lock	= masters_lock
		self.slaves_lock	= slaves_lock
		self.netRing_lock	= netRing_lock
				
		self.Propagate		= Propagate
		
		#Attributs used in Leader election : see  J. Villadangos, A. Cordoba, F. Farina, and M. Prieto, 2005, "Efficient leader election in complete networks"
		self.node 			= LogicalNode( self.get_host(), 
			port, monitors)
		self.client.send( Msg( Action.ALG, (self.node, self.node) ), 
			self.node.succ.host, self.node.succ.port)
		
	def find_port(self):#ON FORCE LE PORT
		self.bind()
		
	def callback(self, data):
		msg	= TcpServer.callback(self, data)
				
		if msg.t == MsgType.ANNOUNCE_SLAVE :
			if( self.ev_leader.is_set() 
			and not self.Propagate.is_set()
			and not msg.obj.id() in self.slaveReports):
				with self.netRing_lock:
					self.client.send( 
						Msg(MsgType.ANNOUNCE_NET_RING, self.netRing), 
						msg.obj.host, msg.obj.port)
			
			with self.slaves_lock:
				self.slaveReports[ msg.obj.id() ] = msg.obj
				
		elif msg.t == MsgType.ANNOUNCE_MASTER:
			if self.ev_leader.is_set():
				with self.slaves_lock:
					for report in msg.obj.netarea_reports:
						self.client.send( 
							Msg(MsgType.ANNOUNCE_SLAVE_MAP, 
							self.slaveReports), 
							report.host, report.port)
				
			with self.masters_lock:
				self.masterReports[ msg.obj.id() ] = msg.obj
		elif msg.t == MsgType.MONITOR_HEARTBEAT:
			with self.monitors_lock:
				self.monitors[ msg.obj.id() ] = msg.obj
				
			with self.netRing_lock:
				self.client.send( 
					Msg(MsgType.ANNOUNCE_NET_RING, self.netRing), 
					msg.obj.host, msg.obj.port)
		elif msg.t == MsgType.ANNOUNCE_NET_RING:
			if not self.ev_leader.is_set():
				with self.netRing_lock:
					self.netRing.update( msg.obj )
		elif msg.t == MsgType.metric_expected:
			host, port = msg.obj
			with self.monitors_lock, self.masters_lock, self.slaves_lock, self.netRing_lock:
				self.client.send( Msg(MsgType.metric_monitor, 
					(self.monitors, self.slaveReports, self.masterReports,
						self.netRing)
					), host, port)
		elif msg.t == Action.ALG :
			i		= self.node
			init,j  = msg.obj #i<-j avec data = init

			if i.status == Status.passive: #msg.obj is a logicalNode
				i.status	= Status.dummy
				self.client.send( Msg( Action.ALG, (init, i) ), 
					i.succ.host, i.succ.port)
			elif i.status == Status.candidate:
				i.cand_pred	= msg.obj
				if i > init:
					if i.cand_succ == None:
						i.status	= Status.waiting
						self.client.send( Msg( Action.AVS, i), 
							init.host, init.port)
					else:
						i.status	= Status.dummy
						self.client.send( 
							Msg( Action.AVSRP, (i.cand_pred,i)), 
							i.cand_succ.host, i.cand_succ.port)

				elif i == init:
					i.status	= Status.leader
					self.ev_leader.set()
		elif msg.t == Action.AVS :
			i,j= self.node, msg.obj
			
			if i.status == Status.candidate :
				if i.cand_pred == None :
					i.cand_succ = j
				else:
					i.status	= Status.dummy
					self.client.send( Msg( Action.AVSRP, i.cand_pred), 
						j.host, j.port)
			elif self.node.status	== Status.waiting:
				self.cand_succ	= j 
		elif msg.t == Action.AVSRP : 
			i	= self.node
			k,j	= msg.obj #k data, j sender
			if i.status == Status.waiting :
				if i == k :
					i.status	= Status.leader
					self.ev_leader.set()
				else:
					i.cand_pred	= k
					if i.cand_succ == None :
						if k<i:
							i.status	= Status.waiting
							self.client.send( Msg(Action.AVS, i), 
								k.host, k.port)
					else:
						i.status	= Status.dummy
						self.client.send( Msg(Action.AVSRP, (k,i)), 
							i.cand_succ.host, i.cand_succ.port )
		else:
			logging.info("Unknow received msg %s" % msg.pretty_str())

class MasterOut(Thread):
	def __init__(self, host, port, monitors, Leader, masterReports, 
		slaveReports,  Exit, monitors_lock, masters_lock, slaves_lock):
		Thread.__init__(self)
		
		self.host			= host
		self.port			= port
		self.monitors		= monitors
		self.slaveReports	= slaveReports
		self.masterReports	= masterReports
		self.Leader			= Leader
		self.Exit			= Exit
		self.monitors_lock	= monitors_lock
		self.masters_lock	= masters_lock
		self.slaves_lock	= slaves_lock
		
		self.client = TcpClient()

	
	def run(self):
		while not self.Exit.is_set():
			if self.Leader.is_set():
				with self.monitors_lock:
					msg2 			= Msg(MsgType.ANNOUNCE_MONITORS, 
						self.monitors)
					
				with self.slaves_lock:
					msg1 			= Msg(MsgType.ANNOUNCE_SLAVE_MAP, 
						self.slaveReports)
						
					with self.masters_lock:
						for master in self.masterReports.values():
							self.client.send( msg2, master.host, 
								master.port )
							
							for report in master.netarea_reports:
								self.client.send( msg1, report.host, 
									report.port )
							
							
						for report in self.slaveReports.values():
							self.client.send( msg2, report.host, 
								report.port )

			#heartbeat
			with self.monitors_lock:
				for m_host, m_port in self.monitors :
					if m_host != self.host:
						self.client.send( Msg(MsgType.MONITOR_HEARTBEAT, 
						MonitorReport(self.host, self.port)), m_host, m_port )
					else:
						self.monitors[ (self.host, self.port) ].reset() 
			sleep(1)
					
class Monitor(Thread):
	def __init__(self, port, monitors, limitFreeMasters):
		"""
			@param limitFreeMasters - minimum number of master which are not overload in the cluster
		"""
		
		self.monitors			= {}
		for host, port in monitors:
			mon	= MonitorReport(host, port)
			self.monitors[  (mon.host, mon.port) ] = mon
			
		self.limitFreeMasters 	= limitFreeMasters
		self.Exit 				= Event()
		self.Leader 			= Event()
		self.Propagate 			= Event()
		
		self.masterReports 		= {} #received reports from masters
		self.slaveReports 		= {} 
		self.netRing			= NetRing()
				
		self.monitors_lock		= RLock()
		self.masters_lock		= RLock()
		self.slaves_lock		= RLock()
		self.netRing_lock		= RLock()
		
		self.server				= MonServer( port,
			self.monitors,
			self.Leader,
			self.masterReports,
			self.slaveReports,
			self.netRing,
			self.Exit,
			self.monitors_lock,
			self.masters_lock,
			self.slaves_lock,
			self.netRing_lock, 
			self.Propagate)
		self.host				= self.server.get_host()
		self.port				= port
		self.masterOut			= MasterOut( self.host,
			self.port,
			self.monitors, 
			self.Leader, 
			self.masterReports, 
			self.slaveReports, 
			self.Exit,
			self.monitors_lock,
			self.masters_lock,
			self.slaves_lock)

		self.client 			= TcpClient()
		logging.debug("Monitor initialized")
		
	def terminate(self):
		self.Exit.set()
		logging.info("Monitor stoped")

	def is_overload(self, masters):
		for report in masters:
			for netarea in report.netarea_reports:
				if netarea.is_overload():
					return True
		return False
		
	def first_allocation(self):
		print("first allocation")
		with self.masters_lock:
			masters =  deepcopy( list(self.masterReports.values() ))
		
		max_netareas = sum([r.maxNumNetareas for r in masters])
		if max_netareas == 0:
			return
		
		free_netareas = int( FIRST_RATE * max_netareas )
		i = 0
		
		begin = 0
		step = ceil(NETAREA_MAX / float(max_netareas-free_netareas))

		for master in masters:
			for j in range( master.maxNumNetareas ):
				if  i < max_netareas-free_netareas :
					net	=NetareaReport(master.host, -1, begin,0, 1<<25, 
						begin+step)
					master.allocate( net )
					begin	+= step
					i+=1
				else:
					break
					
		self.propagate(masters)
				
	def allocate(self, masters, unallocated_netarea):
		"""
			assuming all masters are alive, ie call prune before
		"""
		free_masters = [ master for master in masters if 
			not master.is_overload() ]

		try:
			for netarea in unallocated_netarea:
				free_masters[-1].allocate( netarea )
				if free_masters[-1].is_overload():
					free_masters.pop()
			
			if( sum([ int(not master.is_overload()) 
				for master in masters ]) < self.limitFreeMasters):
				logging.warning( 
					"Masters should be added, system will be overload")
			
		except Exception as e: # if not a free_master remains
			logging.debug( "%s %s" % (
				traceback.extract_tb(sys.exc_info()[2]), str(e)))
			logging.critical( 
				"Masters must be added, system is overload")
				
	def prune(self):
		with self.masters_lock:
			unallocated_netarea	= [ net 
				for report in self.masterReports.values() 
				if( report.is_expired()) 
				for net in report.netarea_reports ]
			del_key	= [ key 
				for key, report in self.masterReports.items() 
				if( report.is_expired()) ]
				
			for key in del_key:
				del self.masterReports[key]
				
		if self.Leader.is_set() :
			masters = []
			with self.masters_lock:
				masters =  deepcopy( list(self.masterReports.values() ))
			if unallocated_netarea:
				with self.netRing_lock:
					for net in unallocated_netarea:
						del self.netRing[ net.netarea ]
				self.allocate( masters, unallocated_netarea)	
				
				
		mon_flag	= False
		with self.monitors_lock :
			for key, monitor in list(self.monitors.items()):
				if monitor.is_expired():
					del self.monitors[ key ]
					mon_flag = True
			
			if mon_flag and not self.Leader.is_set() :
				tmp_node = LogicalNode(self.host, self.port, 
					self.monitors)
				self.client.send( Msg(Action.ALG, (tmp_node, tmp_node)), 
					tmp_node.succ.host, tmp_node.succ.port)
					

		with self.slaves_lock:
			for key, slave in list(self.slaveReports.items()):
				if slave.is_expired():
					logging.debug( slave )
					del self.slaveReports[ key ]
							
	def balance(self):
		with self.masters_lock:
			masters =  deepcopy( list(self.masterReports.values() ))
			
		if sum([ len(r.netarea_reports) for r in self.masterReports.values() ]) == 0:
			self.first_allocation()#No netarea allocated
			return 
		
		if not self.is_overload( masters ):
			with self.netRing_lock and self.masters_lock:
				if not self.netRing:
					self.netRing.update([netarea
						for master in self.masterReports.values()
						for netarea in master.netarea_reports])

			return 
		unallocated_netarea	= []

		for master in masters:
			for netarea in master.netarea_reports:
				if netarea.is_overload():
					net1	= netarea.split()
					
					if not master.is_overload():
						master.allocate( net1 )
					else:
						unallocated_netarea.append(net1)
		
		self.allocate( masters, unallocated_netarea)		
		return masters
		
	def propagate(self, masters):
		self.Propagate.set()
		
		#Stop Slave.sender
		with self.slaves_lock:
			for slave in self.slaveReports.values():
				self.client.send( 
					Msg(MsgType.ANNOUNCE_NET_RING_UPDATE_INCOMING, None), 
					slave.host, slave.port)
		sleep(2)
		
		#Start new netarea
		for master in masters:
			self.client.send( 
				Msg(MsgType.ANNOUNCE_NETAREA_UPDATE, master), 
				master.host, master.port)
				
		sleep(2)#master envoi la reponse toutes les secondes s'il ne répond pas tampis
		
		with self.netRing_lock: 
			self.netRing.update( [ netarea for master in masters
				for netarea in master.netarea_reports] )
			
			with self.masters_lock: 
				for master in self.masterReports.values():
					for netarea in master.netarea_reports:
						self.netRing[ netarea.netarea ] = netarea
		
			netRing = deepcopy( self.netRing )
	
		#Start Slave.sender
		with self.slaves_lock :
			for slave in self.slaveReports.values():			
				self.client.send( 
					Msg(MsgType.ANNOUNCE_NET_RING_PROPAGATE, netRing ), 
					slave.host, slave.port)
		
		with self.monitors_lock:
			for m_host, m_port in self.monitors :
				self.client.send( Msg(MsgType.ANNOUNCE_NET_RING, 
				netRing), m_host, m_port )
		self.Propagate.clear()
		logging.debug("Propagate, done")
		
	def run(self):	
		self.server.start()
		self.masterOut.start()
		
		r = range( 10 if debug else 600)
			
		while True:
			for k in r:
				self.prune()
				sleep(0.1)
				
			if self.Leader.is_set():
				self.balance()
				
			sleep(1)
