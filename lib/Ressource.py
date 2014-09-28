#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  
#	@autor Severus21
#

import SQLFactory

class RessourceManager:
	def __init__(self):
		self.con = SQLFactory.getConn()
		self.table	= ""
		
	def __del__(self):
		self.con.close()
		
	def getByUrl(self, url):
		cur = self.con.cursor()
		cur.execute("SELECT * FROM "+self.table+" WHERE url='"+url+"'")

		r=None
		for row in cur: #url is a unique id
			r=RessourceRecord( row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9] )
		cur.close()
		
		return r
	
	def insert(self, record):
		cur = self.con.cursor()
		cur.execute("INSERT INTO "+self.table+" (url, domain, relatedRessources, sizes, contentTypes, times, md5, lastUpdate)"
					+"VALUES ('"+record.url+"', '"+record.domain+"', '"+record.relatedRessources+"', '"+record.sizes
					+"', '"+record.contentTypes+"', '"+record.times+"', '"+record.md5+"', '"+str(record.lastUpdate)+"')" )
		self.con.commit()
		id = cur.lastrowid
		cur.close()
		return id
		
	def update(self, record):
		cur = self.con.cursor()
		cur.execute("UPDATE urlRecord SET url:='"+record.url+"', domain:='"+record.domain+"', relatedRessources:='"+record.relatedRessources+
					"', sizes:='"+record.sizes+"', contentTypes:='"+record.contentTypes+"', times:='"+record.times+
					+"', md5:='"+record.md5+"', lastUpdate:='"+str(record.lastUpdate)+"' WHERE id='"+str(record.id)+"'" )
		self.con.commit()
		cur.close()
		
	def save(self, record):
		if record.id>-1:
			self.update( record )
		else:
			self.insert( record )
	
class RessourceRecord:
	"""
	"""
	def __init__(self, id=-1, url="", domain="", relatedRessources="", size="", contentTypes="", times="", md5="", lastUpdate=""):
		self.id 				= int(id)
		self.url 				= url
		self.domain 			= domain
		self.relatedRessources 	= relatedRessources
		self.sizes 				= sizes
		self.contentTypes 		= contentTypes
		self.times 				= times
		self.md5 				= md5
		self.lastUpdate 		= float(lastUpdate)

class Ressource:
	"""
	"""
	def __init__(self):
		self.id = -1
		self.url = ""
		self.domain = ""
		self.relatedRessources = [] # [(type, id)]
		
		self.sizes = []
		self.contentTypes = []
		self.times = []
		self.md5 = []
		
		self.lastUpdate = 0
		
		self.data = ""
		
	def hydrate(self, record):
		if record == None:
			return 
		#for key in record.__dict__ :
			#setattr(self, key, getattr(record, key) )
		self.id 				= record.id
		self.url				= record.url
		self.domain				= record.domain
			
		self.relatedRessources	= self.unserializeTupleList( record.relatedRessources )
		self.sizes				= self.unserialiseSimpleList( record.sizes )
		self.contentTypes		= self.unserialiseSimpleList( record.contentTypes )
		self.times				= self.unserialiseSimpleList( record.times )
		self.md5				= self.unserialiseSimpleList( record.md5 )
		
		self.lastUpdate			= record.lastUpdate
	
	def extractUrls(self, parentUrl):
		return []
	
	def serializeSimpleList(self, l):
		s = ""
		for x in l:
			s+=str(x)+":"
		return s[0:len(s)-1]
		
	def unserialiseSimpleList(self, s, f):
		l  = []
		begin=0
		end=0
		i=0
		n=len(s)
		while i<s :
			if( s[i] == ":" ):
				end = i-1
				l.append( f(s[begin, end]) )
				begin = i+1
			i+=1
		return l
		
	def serializeTupleList(self, l):
		s = ""
		for (a,b) in l:
			s+=str(a)+"|"+str(b)+":"
		return s[0:len(s)-1]
		
	def unserializeTuple(self, s, f1, f2):
		find = False
		i=0
		n=len(s)
		while( i<s and find == False):
			if( s[i] == "|"):
				find=True
			i+=1
		
		a = s[0:i-2]
		b = s[i:]
		return( f1(a),f2(b) )
		
	def unserializeTupleList(self, s, f1, f2):
		l  = []
		tmpL = self.unserialiseSimpleList(s)
		for x in tmpL:
			l.append( self.unserializeTuple( x , f1, f2) )
		return l
	
	def getRecord(self):
		return RessourceRecord(
			id					= self.id
			url					= self.url
			domain				= self.domain
			
			relatedRessources	= self.serializeTupleList( self.relatedRessources )
			sizes				= self.serializeSimpleList( self.sizes )
			contentTypes		= self.serializeSimpleList( self.contentTypes )
			times				= self.serializeSimpleList( self.times )
			md5					= self.serializeSimpleList( self.md5 )
			
			lastUpdate			= self.lastUpdate
		)
	
class RessourceHandler:
	def __init__(self, manager):
		self.manager	= manager
	
	def save(self, ressource):
		#SQl
		self.manager.insert( ressource.getRecord() )
		
		#Data		
		
