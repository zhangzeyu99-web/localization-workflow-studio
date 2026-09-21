import unittest
from utils.semantic_constraints import semantic_constraint_issues


class SemanticConstraintTests(unittest.TestCase):
    def test_number_belongs_to_entity(self):
        for lang,target in [('EN','Hero ATK increases by 2% when defending the Base'),('ES','El ATQ del héroe aumenta un 2% al defender la base'),('PT','O ATQ do herói aumenta 2% ao defender a base')]:
            with self.subTest(lang=lang):
                self.assertIn('semantic_entity_number_missing',{x for x,_ in semantic_constraint_issues('编队2英雄防守基地时攻击力提升',target,lang)})

    def test_valid_arabic_roman_and_inflection(self):
        for lang,target in [('EN','Formation II heroes gain ATK when attacking an enemy Base'),('ES','El ATQ de los héroes de la Formación 2 aumenta al atacar una base enemiga'),('PT','O ATQ dos heróis da Formação 2 aumenta ao atacar uma base inimiga')]:
            self.assertEqual(semantic_constraint_issues('编队2英雄攻击敌方基地时攻击力提升',target,lang),[])

    def test_action_and_enemy_are_independent(self):
        source='编队2英雄攻击敌方基地时攻击力提升'
        actual={x for x,_ in semantic_constraint_issues(source,'El ATQ del héroe aumenta al defender la base','ES')}
        self.assertEqual(actual,{'semantic_entity_number_missing','semantic_action_condition_missing','semantic_enemy_scope_missing'})
        self.assertEqual({x for x,_ in semantic_constraint_issues(source,'El ATQ de la Formación 2 aumenta al atacar la base','ES')},{'semantic_enemy_scope_missing'})

    def test_attack_stat_cannot_satisfy_attack_condition(self):
        self.assertIn('semantic_action_condition_missing',{x for x,_ in semantic_constraint_issues('攻击敌方基地时攻击力提升','Attack increases when defending an enemy Base','EN')})

    def test_negation_and_dual_conditions(self):
        self.assertIn('semantic_negation_missing',{x for x,_ in semantic_constraint_issues('无法迁移基地','Puedes trasladar la base','ES')})
        self.assertEqual(semantic_constraint_issues('无法迁移基地','No puedes trasladar la base','ES'),[])
        self.assertEqual(semantic_constraint_issues('攻击时提升攻击力，防守时提升防御力','Gains ATK when attacking and DEF when defending','EN'),[])
