use std::marker::PhantomData;

use libafl::Error;
use libafl::executors::{Executor, ExitKind, HasObservers};
use libafl::state::HasExecutions;
use libafl_bolts::tuples::RefIndexable;

pub struct PlainExecutor<H, OT, I> {
    harness_fn: H,
    observers: OT,
    phantom: PhantomData<I>,
}

impl<H, OT, I> PlainExecutor<H, OT, I>
where
    H: FnMut(&I) -> ExitKind,
{
    pub fn new(harness_fn: H, observers: OT) -> Self {
        Self {
            harness_fn,
            observers,
            phantom: PhantomData,
        }
    }
}

impl<EM, H, I, OT, S, Z> Executor<EM, I, S, Z> for PlainExecutor<H, OT, I>
where
    H: FnMut(&I) -> ExitKind,
    S: HasExecutions,
{
    fn run_target(
        &mut self,
        _fuzzer: &mut Z,
        state: &mut S,
        _mgr: &mut EM,
        input: &I,
    ) -> Result<ExitKind, Error> {
        *state.executions_mut() += 1;
        Ok((self.harness_fn)(input))
    }
}

impl<H, OT, I> HasObservers for PlainExecutor<H, OT, I> {
    type Observers = OT;

    fn observers(&self) -> RefIndexable<&Self::Observers, Self::Observers> {
        RefIndexable::from(&self.observers)
    }

    fn observers_mut(&mut self) -> RefIndexable<&mut Self::Observers, Self::Observers> {
        RefIndexable::from(&mut self.observers)
    }
}
