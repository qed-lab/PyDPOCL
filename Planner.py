#from Flaws import *
from pddlToGraphs import *
import collections
from heapq import heappush, heappop
import itertools
from clockdeco import clock
from Ground import GLib

"""
	Algorithm for Plan-Graph-Space search of Story Plan
"""

class Frontier:
	def __init__(self):
		self._frontier = []

	def __len__(self):
		return len(self._frontier)

	def pop(self):
		return heappop(self._frontier)

	def insert(self, plan):
		heappush(self._frontier, plan)

	def __getitem__(self, position):
		return self._frontier[position]

	def extend(self, itera):
		for item in itera:
			self.insert(item)

import pickle

@clock
def upload(GL):
	afile = open("GL","wb")
	pickle.dump(GL,afile)
	afile.close()

@clock
def reload():
	afile = open("GL","rb")
	GL = pickle.load(afile)
	afile.close()
	return GL


class PlanSpacePlanner:

	def __init__(self, op_graphs, objects, init_action, goal_action, preprocess = False):
		#Assumes these parameters are already read from file

		self.op_graphs = op_graphs
		self.objects = objects

		print('preprocessing...')

		if preprocess:
			self.GL = GLib(op_graphs, objects, Argument.object_types, init_action, goal_action)
			upload(self.GL)
			print(len(self.GL))
		else:
			try:
				print('try to reload:')
				self.GL = reload()
				print(len(self.GL))
			except:
				print('could not reload')
				self.GL = GLib(op_graphs, objects, Argument.object_types, init_action, goal_action)
				upload(self.GL)

		from Relax import RelaxHeuristic
		RelaxHeuristic(self.GL)

		init = copy.deepcopy(self.GL[-2])
		init.replaceInternals()
		goal = copy.deepcopy(self.GL[-1])
		goal.replaceInternals()

		init_plan = PlanElementGraph(uuid.uuid1(0), Elements = objects | init.elements | goal.elements,
									  				 Edges = init.edges | goal.edges)

		init_plan.initial_dummy_step = init.root
		init_plan.final_dummy_step = goal.root

		#create special dummy step for init_graph and add to graphs {}
		self.setup(init_plan, init, goal)
		self.Open =  Frontier()
		self.Open.insert(init_plan)
		print('finished preprocessing...')

	def __len__(self):
		return len(self._frontier)

	def __getitem__(self, position):
		return self._frontier[position]

	def __setitem__(self, plan, position):
		self._frontier[position] = plan

	def setup(self, plan, start_action, end_action):
		"""
			Create step typed element DI, with effect edges to each condition of start_set
			Create step typed element DG, with precondition edges to each condition of end_set
			Add ordering from DI to DG
		"""

		dummy_start = start_action.root
		dummy_final = end_action.root

		plan.OrderingGraph.addOrdering(dummy_start, dummy_final)

		#Add initial Open precondition flaws for dummy step
		init_flaws = (Flaw((dummy_final, prec), 'opf') for prec in plan.getNeighborsByLabel(dummy_final, 'precond-of'))
		for flaw in init_flaws:
			plan.flaws.insert(self.GL, plan, flaw)


	#@clock
	def newStep(self, plan, flaw):
		"""
		@param plan:
		@param flaw:
		@return:
		"""

		results = set()
		s_need, precondition = flaw.flaw

		#antecedent is of the form (antecedent_action_with_missing_eff_link, eff_link)
		antecedents = self.GL.pre_dict[precondition.replaced_ID]
		#print('flaw precondition.replaced_ID: {}'.format(precondition.replaced_ID))
		for ante in antecedents:
			if ante.action.name == 'dummy_init':
				continue

			#step 1 - make a copy
			cndt = copy.deepcopy(ante)

			#step 2 - replace its internals, to distinguish from other identical antesteps
			(anteaction, eff_link) = cndt
			anteaction.replaceInternals()

			#step 3 - make a copy of the plan
			new_plan = plan.deepcopy()

			#step 4 - set sink before replace internals
			preserve_original_id = eff_link.sink.replaced_ID
			eff_link.sink = new_plan.getElementById(precondition.ID)
			eff_link.sink.replaced_ID = preserve_original_id
			# check: eff_link.sink should till be precondition of s_need

			#step 5 - add new stuff to new plan
			new_plan.elements.update(anteaction.elements)
			new_plan.edges.update(anteaction.edges)

			#step 6 - update orderings and causal links, add flaws
			self.addStep(new_plan, anteaction.root, new_plan.getElementById(s_need.ID), eff_link.sink, new=True)
			new_plan.flaws.addCndtsAndRisks(self.GL, anteaction.root)

			#step 7 - add new_plan to open list
			results.add(new_plan)

		return results

	#@clock
	def reuse(self, plan, flaw):
		results = set()
		s_need, precondition = flaw.flaw

		#antecedents - a set of stepnumbers
		antecedents = self.GL.id_dict[precondition.replaced_ID]
		if len(antecedents) == 0:
			return set()

		for s_old in plan.Steps:
			if not s_old.stepnumber in antecedents:
				continue
			if s_old == s_need:
				continue

			#step 1 - make a copy of the plan, also replaces the plan number
			new_plan = plan.deepcopy()

			#step 2 - Actionize the steps from new_plan
			S_Old = Action.subgraph(new_plan, s_old)
			S_Need = Action.subgraph(new_plan, s_need)

			#step 3 - figure out which effect is the dependency
			effect_token = None
			for eff in S_Old.effects:
				if eff.replaced_ID in self.GL.eff_dict[precondition.replaced_ID]:
					effect_token = eff
					break
			if effect_token == None:
				raise AttributeError('GL.eff_dict empty but id_dict has antecedent')


			#step 4 - Remove the precondition and point to the effect_token
			pre_link = new_plan.RemoveSubgraph(precondition)
			pre_link.sink = effect_token

			#step 5 - add orderings, causal links, and create flaws
			self.addStep(new_plan, S_Old.root, S_Need.root, pre_link.sink,  new=False)

			#step 6 - add new plan to open list
			results.add(new_plan)

		return results

	def addStep(self, plan, s_add, s_need, condition, new=None):
		"""
			when a step is added/reused, 
			add causal link and ordering edges (including to dummy steps)
			If step is new, add open precondition flaws for each precondition
		"""
		if new == None:
			new = False

		if not s_add == plan.initial_dummy_step:
			plan.OrderingGraph.addEdge(plan.initial_dummy_step, s_add)
			plan.OrderingGraph.addEdge(plan.initial_dummy_step, s_need)

		if not s_need == plan.final_dummy_step:
			plan.OrderingGraph.addEdge(s_add, plan.final_dummy_step)
			plan.OrderingGraph.addEdge(s_need, plan.final_dummy_step)

		#Always add this ordering
		plan.OrderingGraph.addEdge(s_add, s_need)
		plan.CausalLinkGraph.addEdge(s_add, s_need, condition)

		if new:
			for prec in plan.getIncidentEdgesByLabel(s_add, 'precond-of'):
				plan.flaws.insert(self.GL, plan, Flaw((s_add, prec.sink), 'opf'))

		#Good time as ever to updatePlan
		plan.updatePlan()
		return plan

	#@clock
	def resolveThreatenedCausalLinkFlaw(self, plan, flaw):
		"""
			Promotion: Add ordering from sink to threat, and check if cycle
			Demotion: Add ordering from threat to source, and check if cycle
		"""
		results = set()
		threat, causal_link = flaw.flaw

		#Promotion
		promotion = plan.deepcopy()
		promotion.OrderingGraph.addEdge(causal_link.sink, threat)
		results.add(promotion)


		#Demotion
		demotion = plan.deepcopy()
		demotion.OrderingGraph.addEdge(threat, causal_link.source)
		results.add(demotion)

		return results


	def generateChildren(self, plan, flaw):
		results = set()
		if flaw.name == 'opf':
			results = self.reuse(plan, flaw)
			results.update(self.newStep(plan, flaw))

		if flaw.name == 'tclf':
			results = self.resolveThreatenedCausalLinkFlaw(plan, flaw)

		#for result, res in results:
		for result in results:
			new_flaws = result.detectThreatenedCausalLinks(self.GL)
			result.flaws.threats.update(new_flaws)

		return results

	@clock
	def POCL(self, num_plans = 5):
		Completed = []
		visited = 0
		#Visited = []

		while len(self.Open) > 0:

			#Select child
			plan = self.Open.pop()

			visited+=1

			if not plan.isInternallyConsistent():
				#print('branch terminated')
				continue

			#for step in topoSort(plan):
				#print(Action.subgraph(plan, step))

			if len(plan.flaws) == 0:
				print('solution found at {} nodes visited and {} nodes expanded'.format(visited, len(self.Open)))
				Completed.append(plan)
				if len(Completed) == num_plans:
					return Completed
				continue

			#print(plan)
			#print(plan.flaws)

			#Select Flaw
			flaw = plan.flaws.next()
			#print('selected : {}\n'.format(flaw))

			#Add children to Open List
			children = self.generateChildren(plan, flaw)

			#print('generated children: {}'.format(len(children)))
			for child in children:
				self.Open.insert(child)

			#print('open list number: {}'.format(len(self.Open)))
			#print('\n')

	def makeStepAssignment(self, required_steps):
		Assignment = defaultdict(set)
		for rs in required_steps:
			for gs in self.GL:
				if not rs.isConsistentSubgraph(gs):
					continue
				Assignment[rs.root].add(gs.stepnumber)
		return Assignment



	def integrateRquirements(self, Plan, RQ, RS):
		"""
		For now, we assume no couplings, and therefore all elms are new/replace any existing
		@param Plan:
		@param RQ: Requirement Graph
		@param RS: Restriction Graph
		@return:
		"""
		required_steps = {Action.subgraph(RQ, elm) for elm in RQ.elements if elm.typ == 'Action'}

		#Assignment = collections.namedtuple('Assignment', 'rs gs')

		Assignments = self.makeStepAssignment(required_steps)
		for rs in required_steps:
			if len(Assignments[rs.root]) == 0:
				raise ValueError('empty')

	#	assignments = {Assignment(rs, gs) for rs in required_steps for gs in self.GL if rs.isConsistentSubgraph(gs)}

		orderings = {edge for edge in RQ.edges if edge.label == '<'}
		links = {edge for edge in RQ.edges if type(edge.label) is Literal}

		for link in links:

			#cndt_source_nums = Assignments[link.source]
			cndt_sink_nums = Assignments[link.sink]

			dependency = link.label
			if not dependency is None:
				Dependency = Condition.subgraph(RQ, dependency)

			for csm in cndt_sink_nums:
				if dependency is None:
					Assignments[link.source] = self.GL.ante_dict[csm]

				for pre in self.GL[csm].preconditions:
					if not pre.isConsistent(dependency):
						continue
					Precondition = Condition.subgraph(self.GS[csm], pre)
					if Dependency.Args != Precondition.Args:
						continue

					Assignments[link.source] = self.GL.id_dict[pre.replaced_ID]
					if len(Assignments[link.source]) == 0:
						raise ValueError('um, is this link impossible?')




			for rs, gs in sink_map:
				ante_nums = self.GL.ante_dict[gs.stepnumber]
				for ars, ags in source_map:
					if ags.stepnumber not in ante_nums:
				if dependency is None: #not even a partial literal here

				else:
					Dependency = Condition.subgraph(RQ,dependency)
					#consistent_pretokens = {pre for pre in gs.preconditions if pre.isConsistent(dependency)}
					for pre in gs.preconditions:
						if not pre.isConsistent(dependency):
							continue
						Precondition = Condition.subgraph(gs,pre)
						if Dependency.Args != Precondition.Args:
							continue
						#found consistent precondition
						if rs in


					#if the dependency is a partial literal, then need to pick some consistent precondition.
					#else, find corresponding
					ante_nums = self.GL.id_dict[]
				inconsistent_maps = {asmt for asmt in source_map if asmt[1].stepnumber not in
			self.GL.ante_dict[st.stepnumber] for rs,gs in sink_map



	#@clock
	def integrateRequirements(self, Plan, ReqSteps, ReqLinks, ReqOrderings):
		S = Plan.Steps
		D = self.op_graphs
		TMap = {t: {s for s in S if t.isIsomorphicSubgraphOf(s, consistency=True)}
				for t in ReqSteps}
		DMap = {t: {d for d in D if t.isIsomorphicSubgraphOf(d, consistency=True)}
				for t in ReqSteps}

		for (ti, tj) in ReqOrderings:
			removable = {(si, sj) for si in TMap[ti] for sj in TMap[tj] if Plan.OrderingGraph.isPath(sj, si)}
			for (si, sj) in removable:
				TMap[ti] -= si
				TMap[tj] -= sj

		TMap.update(DMap)
		for (ti, tj, te) in ReqLinks:
			removable = {(si, sj) for si in TMap[ti] for sj in TMap[tj] if Plan.OrderingGraph.isPath(sj, si)}
			for (si, sj) in removable:
				TMap[ti] -= si
				TMap[tj] -= sj

			removable = {(si, sj) for si in TMap[ti] for sj in TMap[tj] if
						 not si.isConsistentAntecedentFor(sj, effect=te)}
			for (si, sj) in removable:
				TMap[ti] -= si
				TMap[tj] -= sj

		return TMap

@clock
def preprocessDomain(operators):
	#get all effect predicates
	pred_set = set()
	for op in operators:
		pred_set.update({eff.name for eff in  op.getNeighborsByLabel(op.root, 'effect-of')})
	return pred_set

def topoSort(graph):
	OG  = copy.deepcopy(graph.OrderingGraph)
	L =[]
	S = {graph.initial_dummy_step}
	while len(S) > 0:
		n = S.pop()
		L.append(n)
		for m_edge in OG.getIncidentEdges(n):
			OG.edges.remove(m_edge)
			if len({edge for edge in OG.getParents(m_edge.sink)}) == 0:
				S.add(m_edge.sink)
	if len(OG.edges) > 0:
		print('error')
		return
	return L

def obTypesDict(object_types):
	obtypes = defaultdict(set)
	for t in object_types:
		obtypes[t.name].add(t.parent)
		accumulated = set()
		rFollowHierarchy(object_types, t.parent, accumulated)
		obtypes[t.name].update(accumulated)
	return obtypes


def rFollowHierarchy(object_types, child_name, accumulated = set()):
	for ob in object_types:
		if not ob.name in accumulated:
			if ob.name == child_name:
				accumulated.add(ob.parent)
				rFollowHierarchy(object_types, ob.parent, accumulated)


import sys

# import unittest
# class TestRequirements(unittest.TestCase):
# 	def testIntegrateRequirements(self):



if __name__ ==  '__main__':
	num_args = len(sys.argv)
	if num_args >1:
		domain_file = sys.argv[1]
		if num_args > 2:
			problem_file = sys.argv[2]
	else:
		#domain_file = 'domains/mini-indy-domain.pddl'
		#problem_file = 'domains/mini-indy-problem.pddl'
		domain_file = 'domains/ark-domain.pddl'
		problem_file = 'domains/ark-problem.pddl'

	#f = open('workfile', 'w')
	operators, objects, object_types, initAction, goalAction = parseDomainAndProblemToGraphs(domain_file, problem_file)
	#non_static_preds = preprocessDomain(operators)
	FlawLib.non_static_preds = preprocessDomain(operators)
	obtypes = obTypesDict(object_types)

	Argument.object_types = obtypes
	planner = PlanSpacePlanner(operators, objects, initAction, goalAction)
	#planner.GL = GLib(operators, objects, obtypes, initAction, goalAction)

	results = planner.POCL(1)

	for result in results:
		totOrdering = topoSort(result)
		print('\n\n\n')
		for step in topoSort(result):
			print(Action.subgraph(result, step))
		#print(result)

	#print('\n\n\n')
	#print(result)
