"""
Generate a GQL Schema string from Pydantic types defined in bindables.
"""
import inspect
import logging
from typing import List
from typing import Set
from typing import Tuple
from typing import Type   # TYP001

from pydantic import BaseModel
from pydantic import Field

from utils import to_camel_case
from utils import translate_filed_model_to_gql_type
from utils import translate_py_type_to_gql_type

logger = logging.getLogger(__name__)


class GQLOperation(BaseModel):
    filed_name: str
    return_type: str

    def to_gql_str(self):
        return f'{self.filed_name}:{self.return_type}'


class GQLSchema(BaseModel):
    query: List[GQLOperation] = Field([])
    mutation: List[GQLOperation] = Field([])
    subscription: List[GQLOperation] = Field([])
    user_defined_types: Set[Type] = Field(default_factory=set)

    def add_operation(self, operation_type, operation):
        getattr(self, operation_type.lower()).append(operation)

    def _scan_all_user_defined_models(self):
        collected_user_types = set()
        user_defined_types_list = list(self.user_defined_types)

        while user_defined_types_list:
            pending_type = user_defined_types_list.pop()
            if pending_type not in collected_user_types:
                collected_user_types.add(pending_type)

                for _, field_model in pending_type.__fields__.items():
                    if issubclass(field_model.type_, BaseModel):
                        user_defined_types_list.append(field_model.type_)

        self.user_defined_types |= collected_user_types

    def _get_user_defined_type_str(
        self, user_type: Type,
    ) -> str:

        schema_type = 'type'
        user_type_str = f'\n {schema_type} {user_type.__qualname__}' + '{'
        for filed_name, field_model in user_type.__fields__.items():
            user_type_str += (
                f'\n{to_camel_case(filed_name)}: '
                f'{translate_filed_model_to_gql_type(field_model)}'
            )
        user_type_str += '\n }'
        return user_type_str

    def to_gql_schema_str(self) -> str:
        self._scan_all_user_defined_models()

        schema_str = ''

        # operations
        for op_type in ('query', 'mutation', 'subscription'):
            if not getattr(self, op_type):
                continue
            op_type_str = f'\n type {op_type.title()}' + ' {'
            for op in getattr(self, op_type):
                op_type_str += f'\n {op.to_gql_str()}'
            op_type_str += '\n }'
            schema_str += op_type_str

        # user defined types
        for user_type in self.user_defined_types:
            user_type_str = self._get_user_defined_type_str(user_type)
            schema_str += user_type_str
        logger.info(f'generated schema: {schema_str}')
        return schema_str


def _get_return_type_from_resolver(resolver) -> Tuple[str, Set[Type]]:
    user_defined_types = set()

    return_annotation = inspect.signature(resolver).return_annotation

    if hasattr(return_annotation, '_name') and return_annotation._name == 'List':
        return_type_inside_list = return_annotation.__args__[0]
        return_type_gql = f'[{translate_py_type_to_gql_type(return_type_inside_list)}]'

        if issubclass(return_type_inside_list, BaseModel):
            user_defined_types.add(return_type_inside_list)

    else:
        return_type_gql = translate_py_type_to_gql_type(return_annotation)
        if issubclass(return_annotation, BaseModel):
            user_defined_types.add(return_annotation)

    return return_type_gql, user_defined_types


def generate_gql_schema(bindables) -> GQLSchema:
    gql_schema = GQLSchema()

    for bindable in bindables:  # Query, Mutation, or Subscription
        # skip bindables dont have _resolvers, e.g. UnionType
        if not hasattr(bindable, '_resolvers'):
            continue

        name = bindable.name
        for field, resolver in bindable._resolvers.items():  # for each resolver
            # collect return type
            (
                return_type_gql,
                user_defined_types_in_return,
            ) = _get_return_type_from_resolver(resolver)

            gql_schema.add_operation(
                name,
                GQLOperation(
                    filed_name=field, return_type=return_type_gql,
                ),
            )
            gql_schema.user_defined_types |= user_defined_types_in_return
    return gql_schema


def generate_gql_schema_str(bindables) -> str:
    return generate_gql_schema(bindables).to_gql_schema_str()
