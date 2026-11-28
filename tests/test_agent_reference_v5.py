import asyncio
import json
import pytest
from app.agent_workflow import references, entities
from app.agent_workflow.state import AgentRuntimeContext

HISTORY=[{'role':'user','content':'列几个公司'}, {'role':'assistant','content':'1. 苹果（Apple，AAPL）\n2. 微软（Microsoft，MSFT）'}]

def test_server_item_identity_restores_original_label_and_rejects_foreign_source():
    catalogue=references.assistant_item_catalogue(HISTORY)
    source=catalogue[0]['source'];item=catalogue[0]['items'][1]
    ref=references.Referent(mention='第二个',source=source,item_id=item['item_id'])
    verified=references.validate_referents([ref],'查第二个',HISTORY,[])
    assert verified[0]['text']=='微软（Microsoft，MSFT）'
    with pytest.raises(ValueError):
        references.validate_referents([references.Referent(mention='第二个',source='assistant_message:'+'a'*20,item_id=item['item_id'])],'查第二个',HISTORY,[])

def test_reference_item_does_not_trust_retyped_model_text():
    catalogue=references.assistant_item_catalogue(HISTORY);item=catalogue[0]['items'][1]
    ref=references.Referent(mention='第二个',text='Apple',source=catalogue[0]['source'],item_id=item['item_id'])
    assert references.validate_referents([ref],'第二个',HISTORY,[])[0]['text']=='微软（Microsoft，MSFT）'

def test_valid_item_id_cannot_select_the_wrong_requested_position():
    catalogue=references.assistant_item_catalogue(HISTORY);item=catalogue[0]['items'][0]
    ref=references.Referent(mention='第二个',source=catalogue[0]['source'],item_id=item['item_id'])
    with pytest.raises(ValueError,match='position'):
        references.validate_referents([ref],'解释第二个',HISTORY,[])

