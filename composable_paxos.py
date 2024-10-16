'''
This module provides an implementation of the Paxos algorithm as
a set of composable classes. 
这个模块提供了Paxos算法的实现，作为一组可组合的类。
'''

import collections

# ProposalID
#
# In order for the Paxos algorithm to function, all proposal ids must be
# unique. A simple way to ensure this is to include the proposer's unique
# id in the proposal id. 
# 为了使Paxos算法正常运行，所有提案ID必须是唯一的。
# 确保这一点的一个简单方法是将提案者的唯一ID包含在提案ID中。
#
# Python tuples allow the proposal number and the UID to be combined in a
# manner that supports comparison in the expected manner:
# Python元组允许将提案编号和UID组合在一起，以支持预期的比较方式：
#
#   (4,'C') > (4,'B') > (3,'Z')
#
# Named tuples from the collections module support all of the regular
# tuple operations but additionally allow access to the contents by
# name so the numeric component of the proposal ID may be referred to
# via 'proposal_id.number' instead of 'proposal_id[0]'.
# collections模块中的命名元组支持所有常规的元组操作，但另外允许通过名称访问内容，
# 因此提案ID的数字组件可以通过'proposal_id.number'而不是'proposal_id[0]'来引用。
#
ProposalID = collections.namedtuple('ProposalID', ['number', 'uid'])

class PaxosMessage (object):
    '''
    Base class for all messages defined in this module
    这个模块中定义的所有消息的基类
    '''
    from_uid = None # Set by subclass constructor 由子类构造函数设置

class Prepare (PaxosMessage):
    '''
    Prepare messages should be broadcast to all Acceptors.
    Prepare消息应广播给所有接受者。
    '''
    def __init__(self, from_uid, proposal_id):
        self.from_uid    = from_uid
        self.proposal_id = proposal_id

class Nack (PaxosMessage):
    '''
    NACKs are technically optional though few practical applications will
    want to omit their use. They are used to signal a proposer that their
    current proposal number is out of date and that a new one should be
    chosen. NACKs may be sent in response to both Prepare and Accept
    messages
    NACK在技术上是可选的，尽管很少有实际应用会希望省略它们的使用。
    它们用于向提案者发出信号，表明其当前的提案编号已过时，应选择新的编号。
    NACK可以作为对Prepare和Accept消息的响应发送。
    '''
    def __init__(self, from_uid, proposer_uid, proposal_id, promised_proposal_id):
        self.from_uid             = from_uid
        self.proposal_id          = proposal_id
        self.proposer_uid         = proposer_uid
        self.promised_proposal_id = promised_proposal_id

class Promise (PaxosMessage):
    '''
    Promise messages should be sent to at least the Proposer specified in
    the proposer_uid field
    Promise消息应至少发送给proposer_uid字段中指定的提案者。
    '''
    def __init__(self, from_uid, proposer_uid, proposal_id, last_accepted_id, last_accepted_value):
        self.from_uid             = from_uid
        self.proposer_uid         = proposer_uid
        self.proposal_id          = proposal_id
        self.last_accepted_id     = last_accepted_id
        self.last_accepted_value  = last_accepted_value

class Accept (PaxosMessage):
    '''
    Accept messages should be broadcast to all Acceptors
    Accept消息应广播给所有接受者。
    '''
    def __init__(self, from_uid, proposal_id, proposal_value):
        self.from_uid       = from_uid
        self.proposal_id    = proposal_id
        self.proposal_value = proposal_value

class Accepted (PaxosMessage):
    '''
    Accepted messages should be sent to all Learners
    Accepted消息应发送给所有学习者。
    '''
    def __init__(self, from_uid, proposal_id, proposal_value):
        self.from_uid       = from_uid
        self.proposal_id    = proposal_id
        self.proposal_value = proposal_value

class Resolution (PaxosMessage):
    '''
    Optional message used to indicate that the final value has been selected
    可选消息，用于指示已选择最终值。
    '''
    def __init__(self, from_uid, value):
        self.from_uid = from_uid
        self.value    = value

class InvalidMessageError (Exception):
    '''
    Thrown if a PaxosMessage subclass is passed to a class that does not
    support it
    如果将PaxosMessage子类传递给不支持它的类，则抛出此异常。
    '''

class MessageHandler (object):
    def receive(self, msg):
        '''
        Message dispatching function. This function accepts any PaxosMessage subclass and calls
        the appropriate handler function
        消息分发函数。此函数接受任何PaxosMessage子类并调用适当的处理函数。
        '''
        handler = getattr(self, 'receive_' + msg.__class__.__name__.lower(), None)
        if handler is None:
            raise InvalidMessageError('Receiving class does not support messages of type: ' + msg.__class__.__name__)
        return handler( msg )

class Proposer (MessageHandler):
    '''
    The 'leader' attribute is a boolean value indicating the Proposer's
    belief in whether or not it is the current leader. This is not a reliable
    value as multiple nodes may simultaneously believe themselves to be the
    leader. 
    'leader'属性是一个布尔值，表示提案者是否认为自己是当前的领导者。
    这不是一个可靠的值，因为多个节点可能同时认为自己是领导者。
    '''
    
    leader               = False
    proposed_value       = None
    proposal_id          = None
    highest_accepted_id  = None
    promises_received    = None
    nacks_received       = None
    current_prepare_msg  = None
    current_accept_msg   = None

    def __init__(self, network_uid, quorum_size):
        self.network_uid         = network_uid
        self.quorum_size         = quorum_size
        self.proposal_id         = ProposalID(0, network_uid)
        self.highest_proposal_id = ProposalID(0, network_uid)

    def propose_value(self, value):
        '''
        Sets the proposal value for this node iff this node is not already aware of
        a previous proposal value. If the node additionally believes itself to be
        the current leader, an Accept message will be returned
        如果该节点尚未知道先前的提案值，则为该节点设置提案值。
        如果该节点还认为自己是当前的领导者，则会返回一个Accept消息。
        '''
        if self.proposed_value is None:
            self.proposed_value = value
            
            if self.leader:
                self.current_accept_msg = Accept(self.network_uid, self.proposal_id, value)
                return self.current_accept_msg

    def prepare(self):
        '''
        Returns a new Prepare message with a proposal id higher than
        that of any observed proposals. A side effect of this method is
        to clear the leader flag if it is currently set.
        返回一个新的Prepare消息，其提案ID高于任何观察到的提案ID。
        此方法的一个副作用是清除当前设置的领导者标志。
        '''
        self.leader              = False
        self.promises_received   = set()
        self.nacks_received      = set()
        self.proposal_id         = ProposalID(self.highest_proposal_id.number + 1, self.network_uid)
        self.highest_proposal_id = self.proposal_id
        self.current_prepare_msg = Prepare(self.network_uid, self.proposal_id)
        return self.current_prepare_msg

    def observe_proposal(self, proposal_id):
        '''
        Optional method used to update the proposal counter as proposals are
        seen on the network.  When co-located with Acceptors and/or Learners,
        this method may be used to avoid a message delay when attempting to
        assume leadership (guaranteed NACK if the proposal number is too low).
        This method is automatically called for all received Promise and Nack
        messages.
        可选方法，用于在网络上看到提案时更新提案计数器。当与接受者和/或学习者共同定位时，
        此方法可用于避免在尝试担任领导职务时的消息延迟（如果提案编号太低，则保证NACK）。
        此方法会自动为所有收到的Promise和Nack消息调用。
        '''
        if proposal_id > self.highest_proposal_id:
            self.highest_proposal_id = proposal_id

    def receive_nack(self, msg):
        '''
        Returns a new Prepare message if the number of Nacks received reaches
        a quorum.
        如果收到的Nack数量达到法定人数，则返回一个新的Prepare消息。
        '''
        self.observe_proposal( msg.promised_proposal_id )
        
        if msg.proposal_id == self.proposal_id and self.nacks_received is not None:
            self.nacks_received.add( msg.from_uid )
            if len(self.nacks_received) == self.quorum_size:
                return self.prepare() # Lost leadership or failed to acquire it

    def receive_promise(self, msg):
        '''
        Returns an Accept messages if a quorum of Promise messages is achieved
        如果达到法定人数的Promise消息，则返回一个Accept消息。
        '''
        self.observe_proposal( msg.proposal_id )
        if not self.leader and msg.proposal_id == self.proposal_id and msg.from_uid not in self.promises_received:
            self.promises_received.add( msg.from_uid )
            if msg.last_accepted_id > self.highest_accepted_id:
                self.highest_accepted_id = msg.last_accepted_id
                if msg.last_accepted_value is not None:
                    self.proposed_value = msg.last_accepted_value
            if len(self.promises_received) == self.quorum_size:
                self.leader = True
                if self.proposed_value is not None:
                    self.current_accept_msg = Accept(self.network_uid, self.proposal_id, self.proposed_value)
                    return self.current_accept_msg

class Acceptor (MessageHandler):
    '''
    Acceptors act as the fault-tolerant memory for Paxos. To ensure correctness
    in the presense of failure, Acceptors must be able to remember the promises
    they've made even in the event of power outages. Consequently, any changes
    to the promised_id, accepted_id, and/or accepted_value must be persisted to
    stable media prior to sending promise and accepted messages.
    When an Acceptor instance is composed alongside a Proposer instance, it
    is generally advantageous to call the proposer's observe_proposal()
    method when methods of this class are called.
    接受者充当Paxos的容错内存。为了确保在故障情况下的正确性，
    接受者必须能够记住他们做出的承诺，即使在停电的情况下也是如此。
    因此，在发送Promise和Accepted消息之前，
    必须将对promised_id、accepted_id和/或accepted_value的任何更改持久化到稳定的介质中。
    当接受者实例与提案者实例一起组成时，通常有利于在调用此类的方法时调用提案者的observe_proposal()方法。
    '''
    def __init__(self, network_uid, promised_id=None, accepted_id=None, accepted_value=None):
        '''
        promised_id, accepted_id, and accepted_value should be provided if and only if this
        instance is recovering from persistent state.
        仅当此实例从持久状态恢复时，才应提供promised_id、accepted_id和accepted_value。
        '''
        self.network_uid    = network_uid
        self.promised_id    = promised_id
        self.accepted_id    = accepted_id
        self.accepted_value = accepted_value

    def receive_prepare(self, msg):
        '''
        Returns either a Promise or a Nack in response. The Acceptor's state must be persisted to disk
        prior to transmitting the Promise message.
        返回Promise或Nack作为响应。在传输Promise消息之前，必须将接受者的状态持久化到磁盘。
        '''
        if msg.proposal_id >= self.promised_id:
            self.promised_id = msg.proposal_id
            return Promise(self.network_uid, msg.from_uid, self.promised_id, self.accepted_id, self.accepted_value)
        else:
            return Nack(self.network_uid, msg.from_uid, msg.proposal_id, self.promised_id)

    def receive_accept(self, msg):
        '''
        Returns either an Accepted or Nack message in response. The Acceptor's state must be persisted
        to disk prior to transmitting the Accepted message.
        返回Accepted或Nack消息作为响应。在传输Accepted消息之前，必须将接受者的状态持久化到磁盘。
        '''
        if msg.proposal_id >= self.promised_id:
            self.promised_id     = msg.proposal_id
            self.accepted_id     = msg.proposal_id
            self.accepted_value  = msg.proposal_value
            return Accepted(self.network_uid, msg.proposal_id, msg.proposal_value)
        else:
            return Nack(self.network_uid, msg.from_uid, msg.proposal_id, self.promised_id)

class Learner (MessageHandler):
    '''
    This class listens to Accepted messages, determines when the final value is
    selected, and tracks which peers have accepted the final value.
    这个类监听Accepted消息，确定何时选择最终值，并跟踪哪些对等方接受了最终值。
    '''
    class ProposalStatus (object):
        __slots__ = ['accept_count', 'retain_count', 'acceptors', 'value']
        def __init__(self, value):
            self.accept_count = 0
            self.retain_count = 0
            self.acceptors    = set()
            self.value        = value

    def __init__(self, network_uid, quorum_size):
        self.network_uid       = network_uid
        self.quorum_size       = quorum_size
        self.proposals         = dict() # maps proposal_id => ProposalStatus 映射proposal_id到ProposalStatus
        self.acceptors         = dict() # maps from_uid => last_accepted_proposal_id 映射from_uid到last_accepted_proposal_id
        self.final_value       = None
        self.final_acceptors   = None   # Will be a set of acceptor UIDs once the final value is chosen 一旦选择了最终值，将是接受者UID的集合
        self.final_proposal_id = None

    def receive_accepted(self, msg):
        '''
        Called when an Accepted message is received from an acceptor. Once the final value
        is determined, the return value of this method will be a Resolution message containing
        the consentual value. Subsequent calls after the resolution is chosen will continue to add
        new Acceptors to the final_acceptors set and return Resolution messages.
        当从接受者收到Accepted消息时调用。一旦确定了最终值，此方法的返回值将是包含一致值的Resolution消息。
        在选择解决方案后的后续调用将继续将新的接受者添加到final_acceptors集合中并返回Resolution消息。
        '''
        if self.final_value is not None:
            if msg.proposal_id >= self.final_proposal_id and msg.proposal_value == self.final_value:
                self.final_acceptors.add( msg.from_uid )
            return Resolution(self.network_uid, self.final_value)
            
        last_pn = self.acceptors.get(msg.from_uid)
        if msg.proposal_id <= last_pn:
            return # Old message 旧消息
        self.acceptors[ msg.from_uid ] = msg.proposal_id
        
        if last_pn is not None:
            ps = self.proposals[ last_pn ]
            ps.retain_count -= 1
            ps.acceptors.remove(msg.from_uid)
            if ps.retain_count == 0:
                del self.proposals[ last_pn ]
        if not msg.proposal_id in self.proposals:
            self.proposals[ msg.proposal_id ] = Learner.ProposalStatus(msg.proposal_value)
        ps = self.proposals[ msg.proposal_id ]
        assert msg.proposal_value == ps.value, 'Value mismatch for single proposal! 单个提案的值不匹配！'
        ps.accept_count += 1
        ps.retain_count += 1
        ps.acceptors.add(msg.from_uid)
        if ps.accept_count == self.quorum_size:
            self.final_proposal_id = msg.proposal_id
            self.final_value       = msg.proposal_value
            self.final_acceptors   = ps.acceptors
            self.proposals         = None
            self.acceptors         = None
            return Resolution( self.network_uid, self.final_value )

class PaxosInstance (Proposer, Acceptor, Learner):
    '''
    Aggregate Proposer, Accepter, & Learner class.
    聚合提案者、接受者和学习者类。
    '''
    def __init__(self, network_uid, quorum_size, promised_id=None, accepted_id=None, accepted_value=None):
        Proposer.__init__(self, network_uid, quorum_size)
        Acceptor.__init__(self, network_uid, promised_id, accepted_id, accepted_value)
        Learner.__init__(self, network_uid, quorum_size)
    def receive_prepare(self, msg):
        self.observe_proposal( msg.proposal_id )
        return super(PaxosInstance,self).receive_prepare(msg)
    def receive_accept(self, msg):
        self.observe_proposal( msg.proposal_id )
        return super(PaxosInstance,self).receive_accept(msg)