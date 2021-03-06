#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Module of the current Interactive Beam environment.

For internal use only; no backwards-compatibility guarantees.
Provides interfaces to interact with existing Interactive Beam environment.
External Interactive Beam users please use interactive_beam module in
application code or notebook.
"""
from __future__ import absolute_import

import importlib
import logging
import sys

import apache_beam as beam
from apache_beam.runners import runner

_interactive_beam_env = None


def current_env(cache_manager=None):
  """Gets current Interactive Beam environment."""
  global _interactive_beam_env
  if not _interactive_beam_env:
    _interactive_beam_env = InteractiveEnvironment(cache_manager)
  return _interactive_beam_env


def new_env(cache_manager=None):
  """Creates a new Interactive Beam environment to replace current one."""
  global _interactive_beam_env
  _interactive_beam_env = None
  return current_env(cache_manager)


class InteractiveEnvironment(object):
  """An interactive environment with cache and pipeline variable metadata.

  Interactive Beam will use the watched variable information to determine if a
  PCollection is assigned to a variable in user pipeline definition. When
  executing the pipeline, interactivity is applied with implicit cache
  mechanism for those PCollections if the pipeline is interactive. Users can
  also visualize and introspect those PCollections in user code since they have
  handles to the variables.
  """

  def __init__(self, cache_manager=None):
    self._cache_manager = cache_manager
    # Holds class instances, module object, string of module names.
    self._watching_set = set()
    # Holds variables list of (Dict[str, object]).
    self._watching_dict_list = []
    # Holds results of pipeline runs as Dict[Pipeline, PipelineResult].
    # Each key is a pipeline instance defined by the end user. The
    # InteractiveRunner is responsible for populating this dictionary
    # implicitly.
    self._pipeline_results = {}
    # Always watch __main__ module.
    self.watch('__main__')
    # Do a warning level logging if current python version is below 3.5.3.
    if sys.version_info < (3, 5, 3):
      self._is_py_version_ready = False
      logging.warning('Interactive Beam requires Python 3.5.3+.')
    else:
      self._is_py_version_ready = True
    # Check if [interactive] dependencies are installed.
    try:
      import IPython  # pylint: disable=unused-import
      import jsons  # pylint: disable=unused-import
      import timeloop  # pylint: disable=unused-import
      from facets_overview.generic_feature_statistics_generator import GenericFeatureStatisticsGenerator  # pylint: disable=unused-import
      self._is_interactive_ready = True
    except ImportError:
      self._is_interactive_ready = False
      logging.warning('Dependencies required for Interactive Beam PCollection '
                      'visualization are not available, please use: `pip '
                      'install apache-beam[interactive]` to install necessary '
                      'dependencies to enable all data visualization features.')

    self._is_in_ipython = False
    self._is_in_notebook = False
    # Check if the runtime is within an interactive environment, i.e., ipython.
    try:
      from IPython import get_ipython  # pylint: disable=import-error
      if get_ipython():
        self._is_in_ipython = True
        if 'IPKernelApp' in get_ipython().config:
          self._is_in_notebook = True
    except ImportError:
      pass
    if not self._is_in_ipython:
      logging.warning('You cannot use Interactive Beam features when you are '
                      'not in an interactive environment such as a Jupyter '
                      'notebook or ipython terminal.')
    if self._is_in_ipython and not self._is_in_notebook:
      logging.warning('You have limited Interactive Beam features since your '
                      'ipython kernel is not connected any notebook frontend.')

  @property
  def is_py_version_ready(self):
    """If Python version is above the minimum requirement."""
    return self._is_py_version_ready

  @property
  def is_interactive_ready(self):
    """If the [interactive] dependencies are installed."""
    return self._is_interactive_ready

  @property
  def is_in_ipython(self):
    """If the runtime is within an IPython kernel."""
    return self._is_in_ipython

  @property
  def is_in_notebook(self):
    """If the kernel is connected to a notebook frontend.

    If not, it could be that the user is using kernel in a terminal or a unit
    test.
    """
    return self._is_in_notebook

  def watch(self, watchable):
    """Watches a watchable.

    A watchable can be a dictionary of variable metadata such as locals(), a str
    name of a module, a module object or an instance of a class. The variable
    can come from any scope even local. Duplicated variable naming doesn't
    matter since they are different instances. Duplicated variables are also
    allowed when watching.
    """
    if isinstance(watchable, dict):
      self._watching_dict_list.append(watchable.items())
    else:
      self._watching_set.add(watchable)

  def watching(self):
    """Analyzes and returns a list of pair lists referring to variable names and
    values from watched scopes.

    Each entry in the list represents the variable defined within a watched
    watchable. Currently, each entry holds a list of pairs. The format might
    change in the future to hold more metadata. Duplicated pairs are allowed.
    And multiple paris can have the same variable name as the "first" while
    having different variable values as the "second" since variables in
    different scopes can have the same name.
    """
    watching = list(self._watching_dict_list)
    for watchable in self._watching_set:
      if isinstance(watchable, str):
        module = importlib.import_module(watchable)
        watching.append(vars(module).items())
      else:
        watching.append(vars(watchable).items())
    return watching

  def set_cache_manager(self, cache_manager):
    """Sets the cache manager held by current Interactive Environment."""
    self._cache_manager = cache_manager

  def cache_manager(self):
    """Gets the cache manager held by current Interactive Environment."""
    return self._cache_manager

  def set_pipeline_result(self, pipeline, result):
    """Sets the pipeline run result. Adds one if absent. Otherwise, replace."""
    assert issubclass(type(pipeline), beam.Pipeline), (
        'pipeline must be an instance of apache_beam.Pipeline or its subclass')
    assert issubclass(type(result), runner.PipelineResult), (
        'result must be an instance of '
        'apache_beam.runners.runner.PipelineResult or its subclass')
    self._pipeline_results[pipeline] = result

  def evict_pipeline_result(self, pipeline):
    """Evicts the tracking of given pipeline run. Noop if absent."""
    return self._pipeline_results.pop(pipeline, None)

  def pipeline_result(self, pipeline):
    """Gets the pipeline run result. None if absent."""
    return self._pipeline_results.get(pipeline, None)

  def is_terminated(self, pipeline):
    """Queries if the most recent job (by executing the given pipeline) state
    is in a terminal state. True if absent."""
    result = self.pipeline_result(pipeline)
    if result:
      return runner.PipelineState.is_terminal(result.state)
    return True
