from numpy import ndarray, \
                  array, \
                  newaxis, \
                  float64, \
                  vectorize, \
                  rollaxis, \
                  indices
from numpy.ma import sum

from perm.SpeciesGroup import Species
from warnings import warn
import operator
import re

ReactionGroup = str

__all__ = ['Stoic', 'ReactionFromString', 'Reaction', 'ReactionArray']


class Stoic(float64):
    """
    Stoic is a sub-class of float with a role
    property.  The role property is 'r', 'p', or 'u'.
    r = reactant
    p = product
    u = undetermined
    
    Undetermined is useful when a species is part of a 
    net reaction and may play either role
    
    Stoic are created by
        Stoic(2., 'r')
    
    Stoic supports:
        __mul__: Stoic*(Stoic|Number)
        __rmul__: (Stoic|Number)*Stoic
        __add__: Stoic+(Stoic|Number)
    """
    def __new__(subtype,f,role):
        result = float64.__new__(subtype,f)
        result.role = role
        return result

    def __mul__(self,rhs):
        return Stoic(float64.__mul__(self,rhs),self.role)

    def __rmul__(self,lhs):
        return Stoic(float64.__mul__(self,lhs),self.role)

    def __add__(self,rhs):
        if isinstance(rhs, Stoic):
            if rhs.role == self.role:
                role = self.role
            else:
                role = 'u'
        else:
            role = self.role
            
        return Stoic(float64.__add__(self,rhs),role)

StoicArray = vectorize(Stoic, otypes = [object])
def AddRole(s1, s2):
    if isinstance(s1,Stoic):
        return s1
    else:
        return Stoic(s1, s2.role)
        
def StoicAdd(s1, s2):
    return Stoic.__add__(AddRole(s1,s2), s2)

StoicAdd = vectorize(StoicAdd, otypes = [object])

def ReactionFromString(rxn_str):
    """
    ReactionFromString is a convenience function.  It creates
    Reaction objects from a string with the following pattern:
        "(?P<reactants>.*)=(?P<rxn_type>[kj])[>]\s*(?P<products>.*)"
    where each reactant or product matches the following pattern:
        "(\s?(?P<sign>[+-])?\s?)?((?P<stoic>\d(\.(\d{1,3}(E\d{2})?)?)?)\*)?(?P<name>[A-Z]\w{0,3})\s?"

    For example:
        OH + OLE =k> 0.8*FORM + 0.33*ALD2 + 0.62*ALDX + 0.8*XO2 + 0.95*HO2 - 0.7 PAR
    """
    stoics = {}
    roles = {}
    species = ()
    
    reaction_re = re.compile("(?P<reactants>.*)=(?P<rxn_type>[kj])[>]\s*(?P<products>.*)")

    species_re = re.compile("(\s?(?P<sign>[+-])?\s?)?((?P<stoic>\d{0,1}(\.(\d{1,3}(E\d{2})?)?)?)\*)?(?P<name>[xyA-Z]\w*)(?:[ +=]|$)+",re.M)
    
    reaction_match = reaction_re.match(rxn_str)
    if reaction_match is None:
        raise SyntaxError, "Reactions must match the following patter\n\n<%d> stoic*spc ([+-] stoic*spc)* =[kju]= [stoic*spc] ([+-] stoic*spc)*"

    reactants = reaction_match.groupdict()['reactants']
    reaction_type = reaction_match.groupdict()['rxn_type']
    products = reaction_match.groupdict()['products']

    for spc in species_re.finditer(reactants):
        spc_g = spc.groupdict()
        name = spc_g['name']
        sign = spc_g['sign']
        stoic = spc_g['stoic']
        if sign is None:
            sign = ''

        if stoic is None:
            stoic = '1'

        if name in species:
            stoics[name] += -float(sign + stoic)
        else:
            species += (name,)
            stoics[name] = -float(sign + stoic)

        roles[name] = 'r'

    
    for spc in species_re.finditer(products):
        spc_g = spc.groupdict()
        name = spc_g['name']
        sign = spc_g['sign']
        stoic = spc_g['stoic']
        if sign is None:
            sign = '+'

        if stoic is None:
            stoic = '1'
        
        value = float(sign + stoic)
        if name in species:
            stoics[name] += value
            role = roles[name]
            if role == 'r':
                role = 'u'
            roles[name] = role
        else:
            stoics[name] = value
            roles[name] = 'p'
            species += (name,)
        
    return Reaction(reaction_type = reaction_type, roles = roles, **stoics)

class Reaction(object):
    """
    Reaction is an object that represents reaction groups.  The simplest
    case being a "single reaction" reaction group.
    
    Reaction groups support the following interfaces

        1) indexing (__getitem__) for stoiciometry
        2) multiplication (__mul__ and __rmul__) by arrays and numbers
        3) addition (__add__) of reactions or species
    
    A Reaction can also determine when a species is a reactant, product 
    or unspecified.  When a species is only present as a one role or the other 
    (reactant or product), it is always that role.  When a species is present 
    in the group as both, its current role is determined by the stoichiometry.
    
    Convenience functions:
        has_spc = spc in Reaction.species()
        has_rct = spc in Reaction.reactants()
        has_prd = spc in Reaction.products()
    
    Other functions:
        add_rct_spc
        add_prd_spc
    """
    def __init__(self, reaction_type = 'k', roles = {}, **stoic):
        """
            roles - dictionary of specific roles; for species whose 
                    stoichiometric sign is inconsistent with their 
                    role (i.e. X + Y =k> Z - .6*PAR)
            reaction_type - 'k' is kinetic, 'j' is photolysis, 'u' is unknown
            stoic - stoichiometry values provided as keywords by species; values
                    can be scalars or ndarrays
        """
        self.reaction_type = reaction_type
        self._species = tuple([k for k in stoic.keys()])
        self._roles = roles.copy()
        self._stoic = stoic.copy()
        
        try:
            self.shape = self._stoic[self._species[0]].shape
        except AttributeError, (e):
            self.shape = ()
            for spc in self._species:
                self._stoic[spc] = float64(self._stoic[spc])
            
        
        for k in self._species:    
            if k not in self._roles:
                self._roles[k] = {True: 'r', False: 'p'}[sum(stoic[k]) < 0]
        self._update_roles()

    def _update_roles(self):
        """
        Create static copy of species roles
        """
        self._reactants = ()
        self._products = ()
        self._unspecified = ()
        
        for k, v in self._roles.iteritems():
            if v == 'r':
                self._reactants += (k,)
            elif v == 'p':
                self._products += (k,)
            elif v == 'u':
                self._unspecified += (k,)
                if sum(self._stoic[k]) > 0:
                    self._products += (k,)
                else:
                    self._reactants += (k,)
    
    def __contains__(self, lhs):
        """
        Test if reaction has a species
        """
        if isinstance(lhs, Species):
            return len(set(lhs.names()).intersection(self._species)) > 0
        elif isinstance(lhs, str):
            return lhs in self._species
        else:
            raise TypeError, 'Unknown comparison: __contains__ for Reaction and %s' % str(type(lhs))
            
    def __getitem__(self, item):
        """
        Return a stoichiometry for a species or, if item is not a species, return
        a new reaction where stoichiometry is subset using item
        """
        if isinstance(item, Species):
            try:
                return self._stoic[item.name]
            except KeyError, (e):
                species = set(item.names()).intersection(self._species)
                if len(species) == 0:
                    raise KeyError, "%s does not contain %s" % (str(self.sum()), str(item))
                
                value = 0
                for spc in species:
                    value = value + item[spc][0] * self._stoic[spc]
                first_spc_role = self._roles[species.pop()]
                same_role = all([first_spc_role == self._roles[spc] for spc in species])
                
                if same_role:
                    role = first_spc_role
                else:
                    role = 'u'
                return Stoic(value, role = role)
        elif isinstance(item, str):
            return Stoic(self._stoic[item], role = self._role)
        else:
            return Reaction(roles = self._roles, reaction_type = self.reaction_type, **dict([(k,v[item]) for k, v in self._stoic.iteritems()]))
    
    def __str__(self):
        """
        Report all values followed by the sum value for the reaction
        """
        result = ''
        temp = self.copy()
        temp.shape = ()
        if self.shape != ():
            result += '%d Reactions with shape %s\n' % (reduce(int.__mul__, self.shape), str(self.shape))
            for idx in indices(self.shape).reshape(len(self.shape), -1).swapaxes(0,1):
                idx = tuple(idx)
                result += str(idx) + ': '
                for spc in self._species:
                    temp._stoic[spc] = self._stoic[spc][idx]
                result += str(temp)+', \n'
            result = result[:-3]+'\n'
        sum_result = self.display(digits = 5, nspc = 1000)

        if result != '':
            result += '-' * (len(sum_result)+5) + '\nSum: '
        result += sum_result
            
        return result

    def __repr__(self):
        """
        Representation is same as string
        """
        return self.__str__()

    def display(self, digits = 5, nspc = 3):
        reactants = [(self._stoic[rct].sum(), rct) for rct in self.reactants()]
        reactants.sort(reverse=False)

        products = [(self._stoic[prd].sum(), prd) for prd in self.products()]
        products.sort(reverse=True)

        if digits == None:
            str_temp = '%s'
            reactant_str = ' + '.join([str_temp % rct for stoic, rct in reactants][:nspc])
            product_str = ' + '.join([str_temp % prd for stoic, prd in products][:nspc])
        else:
            str_temp = '%%.%df*%%s' % digits
            reactant_str = ' + '.join([str_temp % (-1*stoic,rct) for stoic, rct in reactants][:nspc])
            product_str = ' + '.join([str_temp % (stoic,prd) for stoic, prd in products][:nspc])

        if len(reactants) > nspc:
            reactant_str += ' + ...'
        if len(products) > nspc:
            product_str += ' + ...'

        return '%s =%s> %s' % (reactant_str, self.reaction_type, product_str)
        
    def __add__(self,rhs):
        """
        Add reactions to make a net reaction or add species to an existing reaction.
        """
        if isinstance(rhs,Reaction):
            kwds = {}
            
            for spc in self._species:
                kwds[spc] = self._stoic[spc]
            
            for spc in rhs._species:
                if kwds.has_key(spc):
                    kwds[spc] = kwds[spc] + rhs._stoic[spc]
                else:
                    kwds[spc] = rhs._stoic[spc]
            roles = {}
            for spc in set(self._species+rhs._species):
                new_role = ''.join(set(self._roles.get(spc,'') + rhs._roles.get(spc,'')))
                if len(new_role) == 1:
                    roles[spc] = new_role
                else:
                    roles[spc] = 'u'
            
            if self.reaction_type == rhs.reaction_type:
                kwds['reaction_type'] = self.reaction_type
            else:
                kwds['reaction_type'] = 'u'

        elif isinstance(rhs,Species):
            return self.__add_if_in_spclist(rhs,self._species)

        else:
            raise TypeError, "Currently, only reactions can be added together"
        
        return Reaction(**kwds)
        
    def __rmul__(self,irrs):
        return self.__mul__(irrs)
        
    def __mul__(self,irrs):
        species = self._species
        values = dict([(k,v*irrs) for k, v in self._stoic.iteritems()])
        result = Reaction(roles = self._roles, reaction_type = self.reaction_type, **values)
        return result

    def __add_if_in_spclist(self,rhs,spc_list):
        if not self.has_spc(rhs):
            raise KeyError, 'Reaction has no components of %s' % rhs.name
        elif rhs.name in self._species:
            warn('Already has %s' % rhs.name)
            return self.copy()
        elif rhs.exclude:
            raise ValueError, 'Exclude is not supported'
        result = self.copy()
        new_stoic = result[rhs]
        
        result._roles[rhs.name] = new_stoic.role
        result._species += (rhs.name,)
        result._stoic[rhs.name] = new_stoic.view(ndarray)
        result._update_roles()

        return result
            
    def copy(self):
        """
        Create a copy of the reaction such that stoichiometry 
        are not shared
        """
        return Reaction(roles = self._roles, reaction_type = self.reaction_type, **dict([(k, v.copy()) for k, v in self._stoic.iteritems()]))

    def sum(self, axis = None):
        """
        Sum stoichiometries and create a scalar reaction
        """
        result = self.copy()
        for spc in result._species:
            result._stoic[spc] = self._stoic[spc].sum(axis)
        result.shape = ()
        result._update_roles()
        return result
        
    def reactants(self):
        """
        Report all species acting as reactants; includes negative
        stoichiometries for unspecified role species
        """
        return self._reactants
        
    def products(self):
        """
        Report all species acting as products; includes positive
        stoichiometries for unspecified role species
        """
        return self._products
        
    def species(self):
        """
        Report all species
        """
        return self._species

    def unspecified(self):
        """
        Report all species with unspecified roles
        """
        return self._unspecified

    def get(self, item, default = None):
        try:
            return self.__getitem__(item)
        except:
            return default
            

    def has_spc(self,spc_grp):
        return spc_in_list(spc_grp,self._species)
        
    def has_rct(self,spc_grp):
        return spc_in_list(spc_grp,self._reactants)
        
    def has_prd(self,spc_grp):
        return spc_in_list(spc_grp,self._products)
    
    def add_rct_spc(self,rhs):
        return self.__add_if_in_spclist(rhs,self._reactants)
        
        
    def add_prd_spc(self,rhs):
        return self.__add_if_in_spclist(rhs,self._products)

def spc_in_list(spc_grp,local_list):
    if spc_grp.exclude:
        return not spc_in_list(-spc_grp, local_list)
    else:
        for s in spc_grp.names():
            if s in local_list:
                return True
        else:
            return False
