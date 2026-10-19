from aiogram.fsm.state import State, StatesGroup

class TestStates(StatesGroup):
    choosing_category = State() # выбор категории теста
    in_test = State() # прохождение теста 